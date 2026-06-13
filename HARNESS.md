# HARNESS.md — EducationApplicantVerifier

A **harness** that supervises a swappable AI worker reviewing education-sector job
applications. The worker only *proposes* an evaluation; the harness owns
everything around it — it normalizes input, **verifies the applicant's teaching
certificate against the Texas Education Agency (TEA)**, enforces declared
guardrails, gates every output through pass/fail checkpoints, raises structured
alarms, persists each step, escalates to a human when needed, and ranks. Swap the
model and the constraints still hold.

> **Agent = Model + Harness.** This repo is the harness. The model (the "worker")
> is a thin, replaceable brain — Claude, DeepSeek, Groq/Gemma, or a deterministic
> fake — and the harness makes constraint-handling invisible to it.

**Live demo:** frontend `https://eav-web.vercel.app` → backend `https://eav-api.vercel.app`.

---

## What it does

A school administrator picks a **job** (e.g. *IDEA 6–8 Science*, *Fort Bend Early
Childhood Special Education*), sees **candidates**, and clicks one. The harness then:

1. **Verifies the candidate's Texas educator certificate live against TEA** (real lookup).
2. **Scores the candidate against that specific job description** with cited evidence.
3. Returns **Accepted / Rejected / Escalated** with the full reasoning, and shows the
   loop animating end to end.

The same candidate gets different decisions for different jobs and different models —
e.g. Adrian Edmonds is **accepted** for a science role but **rejected** for a
Special-Ed role he isn't certified for.

---

## The four pillars (each a distinct module, separate from the worker)

The worker implements only `Worker.propose(application, rubric, prior_failures) -> Proposal`
— **no I/O, no authority**. The harness owns the four pillars; they are separate,
importable modules the worker never calls into.

### ① Material handling — `material.py`
Clean interfaces in and out. Heterogeneous applications and job descriptions are
normalized to canonical dataclasses (`Application`, job dict); results are rendered
to plain JSON for the API/UI. The worker never touches raw files, HTTP, or enums.

### ② Guardrails (declared) — `guardrails.py`
Declared rules the worker's output must pass, applied **before** the output is
accepted:
- **Grounding** — a claimed qualification may not exceed what the document supports
  (`UNGROUNDED_CLAIM`).
- **Bias** — no protected-class / age-coded language (whole-word matched, so "old"
  doesn't fire inside "household").
- **Score range** — overall score must be 0–10.

Rules are listed in code (`BANNED_TERMS`, explicit checks), not buried in a prompt —
that is what "declared, not implicit" means.

### ③ Checkpoints (explicit pass/fail, persisted) — `checkpoints.py`
- **Evaluation checkpoint** — schema valid, every criterion scored **with a cited
  evidence span**, recommendation is `advance`/`reject`.
- **Credential hard-gate** — uses the verifier (tool) result to decide eligibility:
  valid → eligible; expired/not-found → ineligible; name-mismatch (fraud) or tool
  unavailable → escalate.

Each applicant's result is persisted (`store.py`) and replayable.

### ④ Alarms (structured) — `alarms.py`
A **declared catalog**: each named type maps to a severity and a recommended action.
Every alarm in the system is structured `{type, severity, context, recommended_action}` —
never ad-hoc. Types include `HALLUCINATED_QUALIFICATION`, `BIAS_DETECTED`,
`MISSING_CITATION`, `CERT_EXPIRED`, `CERT_NOT_FOUND`, `CERT_MISMATCH`,
`TOOL_UNAVAILABLE`, `RETRY_BUDGET_EXCEEDED`.

---

## The loop (and the behavior-changes-on-feedback requirement)

`harness.py`, per applicant under the active `RoleProfile`:

```
Material In ─▶ Verify credential (TEA tool) ─▶ hard-gate
                                                  │ eligible
                                                  ▼
                 ┌────────── WORKER.propose (scores vs the job) ◀───────┐
                 ▼                                                       │
            ② Guardrails + ③ Checkpoint ──fail──▶ return the specific ──┘
                 │ pass                            failure → worker REVISES
                 ▼                                 (bounded; else escalate to human)
            persist ─▶ rank deterministically (the harness sorts, not the model)
```

**This is the MUST: the worker's behavior changes based on guardrail/checkpoint
feedback.** When a checkpoint rejects an evaluation (e.g. a score with no cited
evidence, or a claim not grounded in the document), the harness returns that exact
failure and the worker re-proposes for the *same* applicant. It loops up to
`max_attempts`, then **escalates to a human** (`RETRY_BUDGET_EXCEEDED`) rather than
guessing. The harness also catches a worker that errors or returns unparseable JSON
and treats it as a failed attempt — a misbehaving model can't crash the run.

---

## Swappable worker (the model) — `worker.py`

All workers share one interface, so the harness is identical regardless of model:

| Worker | Model | Notes |
|---|---|---|
| `LLMWorker` | Claude (default `claude-haiku-4-5`) | Anthropic SDK |
| `GroqWorker` | Gemma (`gemma2-9b-it`) | Groq OpenAI-compatible API, stdlib only |
| `DeepSeekWorker` | DeepSeek (`deepseek-v4-flash`) | DeepSeek OpenAI-compatible API, stdlib only |

**An LLM is required — there is no fake/offline worker.** With no API key set there
is no worker and the app cannot run a review. Tests mock the model's network call
against these real worker classes, so the suite stays offline and deterministic
without implying the loop works without an LLM.

`GroqWorker` and `DeepSeekWorker` share a 3-constant `_OpenAICompatibleWorker` base —
adding another OpenAI-compatible provider is trivial. A model is offered in the UI
**only when its API key is set**, so you can't pick a worker that can't run. The
worker prompt is **job-aware**: it includes the selected job description and scores
fit against *that* role.

---

## The credential tool (TEA) — `verifier.py`

A `CredentialVerifier` is a harness-owned **tool**; the worker never calls it.

- `TEACredentialVerifier` — queries the real TEA ECOS VirtCert public lookup (a plain
  HTML POST, stdlib only, so it runs on serverless). Parses holder, status, cert type,
  and expiration; modes: `live`, `fixture` (offline), `auto` (live → fixture fallback);
  on failure returns `UNAVAILABLE` so the harness escalates.
- `FakeCredentialVerifier` — in-memory lookup table covering valid / expired /
  not-found / name-mismatch (fraud) / unavailable, for deterministic tests.

This is real, not mocked: a known candidate verifies live as **Valid** with their
actual certificate and expiration. Credential verification is surfaced prominently in
the UI (a dedicated loop stage + a "Checked live against the Texas Education Agency"
banner).

---

## Role Profiles (versatility) — `profiles.py`

A `RoleProfile` bundles `{rubric, required_credential, verifier, pass_score,
max_attempts, guardrail_config}`. The harness runs against a profile, so swapping the
profile retargets the whole harness (e.g. teacher → other education roles) with no
harness changes. Different credentials map cleanly onto the same `CredentialVerifier`
interface — TEA is a single authoritative registry; other domains (e.g. food-handler
cards) are federated across issuers — proving the tool is as swappable as the model.

---

## Observability — `observability.py` + `events.py`

One instrumentation layer, two audiences. The harness emits a `LoopEvent` at every
stage onto an in-process bus; a lightweight `Tracer` records spans and **bridges every
alarm onto the bus** (`alarm` events carry type/severity/action). The dashboard
consumes this stream to animate the loop and explain the decision. The tracer is a
swappable backend — the OTel/OpenLLMetry → Phoenix exporter drops in here without
touching the rest of the harness.

---

## Persistence & replay — `store.py`

Each applicant's completed result is a checkpoint in the run store. On a re-run,
completed applicants are served from the store instead of re-running the worker or the
verifier ("replay skips prior stages"), verified by a test that asserts the verifier
is not re-called on replay.

---

## Architecture

```
education_applicant_verifier/      Python harness core
  types.py        domain types + Worker / CredentialVerifier protocols
  profiles.py     RoleProfile (rubric + verifier + config)
  material.py     ① clean I/O          guardrails.py  ② declared rules
  checkpoints.py  ③ pass/fail + cred hard-gate         alarms.py  ④ declared catalog
  worker.py       Worker protocol · LLMWorker(Claude) · GroqWorker(Gemma) · DeepSeekWorker
  verifier.py     CredentialVerifier · TEACredentialVerifier · FakeCredentialVerifier
  observability.py + events.py   tracer + LoopEvent bus (Phoenix-ready)
  store.py        persistence + replay        harness.py  the instrumented loop
  server.py       FastAPI: /api/jobs, /api/candidates, /api/review   cli.py
ui/               React + TS dashboard (jobs → split JD/candidates → full-width loop)
data/             job_descriptions/ , applicants/ , resumes/
tests/            E2E + per-pillar + worker + telemetry + closure regression (29 tests)
```

**Deployment (Vercel):** backend (`eav-api`) is the FastAPI app as a Python function;
frontend (`eav-web`) is the static React build pointed at the backend. Model API keys
live as encrypted backend env vars (`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, optional
`GROQ_API_KEY`); the frontend never sees them.

---

## Run it

```bash
pip install -r requirements-dev.txt
pytest                                                   # 29 tests, offline & deterministic
python -m education_applicant_verifier.cli data/         # run the harness on samples (CLI)
uvicorn education_applicant_verifier.server:app --reload # dashboard at http://localhost:8000

# real models (optional) — set keys, then the LLM workers appear:
export ANTHROPIC_API_KEY=...      # Claude (claude-haiku-4-5 default; CLAUDE_MODEL to override)
export DEEPSEEK_API_KEY=...       # DeepSeek (deepseek-v4-flash default; DEEPSEEK_MODEL to override)
export GROQ_API_KEY=...           # Gemma (gemma2-9b-it default; GROQ_MODEL to override)
```

The `/api/review` request carries `{applicant, job, worker, verifier}`; send
`verifier:"tea"` for the real credential lookup.

---

## Challenge requirement coverage

| Requirement | Where |
|---|---|
| Four pillars, each a distinct component separate from the worker | `material/guardrails/checkpoints/alarms.py` |
| Agent behavior changes based on guardrail/checkpoint feedback | `harness.py` correction loop (revise-on-failure) |
| Guardrails declared, not implicit | `guardrails.py` (`BANNED_TERMS`, explicit checks) |
| Checkpoints with explicit pass/fail | `checkpoints.py` |
| Alarms structured (type · severity · context · action) | `alarms.py` declared catalog |
| Runs on a real input at demo time | live TEA verification of a real educator + real job postings |
| Swappable worker (drop-in, no harness changes) | `Worker` protocol; 3 LLM implementations; live UI swap |
| Checkpoints persisted / replayable | `store.py` (+ replay test) |
| Human-in-the-loop escalation | hard-gate fraud/unavailable + `RETRY_BUDGET_EXCEEDED` |
| Observability | `observability.py` + `events.py` (Phoenix-ready) |
| Versatility across domains | `RoleProfile` |

## Honest limitations
- The deployed dashboard replays the loop timeline after the run completes; live SSE
  streaming is a planned upgrade.
- Observability ships as an in-house tracer/event bus; the Phoenix/OTel exporter is the
  intended drop-in (the layer is built for it).
- Real TEA verification depends on the public TEA site being reachable; if it's slow or
  down the harness escalates (`TOOL_UNAVAILABLE`) by design.
