# EducationApplicantVerifier — End-to-End Build Plan

A harness that supervises a **swappable AI worker** reviewing **education-sector** applications.
First role: **educator** applicants (teacher / paraprofessional / substitute), with the hard
requirement *"holds a valid Texas educator certificate"* verified live against **TEA** (Texas
Education Agency, ECOS VirtCert). The agent only *proposes*; the harness validates, gates,
alarms, persists, and ranks around it — including catching a fraudulent credential claim.

**Event:** Fired Festival — 24-Hour Build Challenge.
**Deliverables due:** repo URL · deployed harness URL · `HARNESS.md` · 5-min demo video
(Saturday 4:30 PM). Phases are ordered by priority with explicit stop points.

> **Code package:** `education_applicant_verifier` (CLI: `python -m education_applicant_verifier.cli`).
> Short alias `eav` available if the verbosity gets in the way.

---

## Development methodology — Test-Driven Development (TDD)

The whole build is **TDD, E2E-first**, so everything is verified working by submission:

- **Test first, every phase.** Write or extend a test *before* the implementation; implement only
  until it passes. No production code without a failing test that demands it.
- **E2E-first.** The headline end-to-end test (Phase 6) defines "done" for the whole harness and
  runs on every change — it is the contract the rest of the code serves.
- **Every phase has a test gate.** A phase is not complete until its tests are green (see each
  phase's *Exit*).
- **Green = ship-ready.** The full `pytest` suite MUST be green at every phase boundary and
  **must be green before submission**. A green suite is the definition of done for the day.
- **Fast & deterministic.** Tests run offline using fakes for the worker and verifier, so the
  suite is always runnable at zero cost. Real Claude / TEA are integration-tested behind the same
  interfaces using recorded fixtures.
- **Test the harness's own guarantees**, not just the worker: telemetry (in-memory span exporter
  asserts spans + alarms fired), persistence/replay (replay skips completed work), and the gold
  set as a calibration/regression eval.

---

## Locked decisions

| Decision | Choice |
|---|---|
| Name | **EducationApplicantVerifier** |
| First domain | Educator application review + TEA credential verification |
| Harness core | Python |
| UI | **Next.js / React + TS dashboard, no sign-in** |
| Frontend deploy | **Vercel** |
| Backend deploy | **Koyeb** (free, no credit card) — switch to **Google Cloud Run** if testing needs it |
| Observability | **Phoenix** (local dev / sidecar; OTel / OpenLLMetry); OTLP endpoint configurable |
| Worker (the AI) | `FakeWorker` first → real Claude (`LLMWorker`) |
| Verifier (the tool) | `FakeCredentialVerifier` → real `TEACredentialVerifier` |
| Persistence | `Store` interface: filesystem (local) / backend disk or DB (deployed) |
| Versatility | **Role Profiles** — abstraction built in from the start |
| 2nd role (stretch) | **Food handling** profile (DSHS food handler / CFM) — after CORE MVP + Dashboard |
| Evals | pytest-as-evals over a gold set |
| **Method** | **Test-Driven Development, E2E-first (see above)** |

Everything the harness depends on — the worker, the credential tool, and the observability
backend — is **swappable behind an interface** and never imported by the harness directly.

---

## Architecture

```
education_applicant_verifier/    # Python harness core (deployed on Koyeb)
  types.py        domain types + Worker / CredentialVerifier Protocols
  profiles.py     RoleProfile (rubric + required creds + verifier + guardrail config)
  observability.py OTel/OpenLLMetry tracer → Phoenix; metrics; alarm→span bridge
  events.py       LoopEvent types + bus (UI projection of the same telemetry)
  alarms.py       (4) declared alarm catalog: type -> severity + recommended action
  worker.py       Worker protocol · FakeWorker · LLMWorker (Claude)
  verifier.py     CredentialVerifier · FakeCredentialVerifier · TEACredentialVerifier
                  · FoodHandlerVerifier (stretch)
  material.py     (1) applications in -> schema / ranked result out
  guardrails.py   (2) declared rules: grounding, bias, PII, score range
  checkpoints.py  (3) schema/citation/calibration + credential hard-gate
  store.py        persistence + replay (filesystem | DB adapters)
  harness.py      the loop, instrumented end to end; runs against a RoleProfile
  cli.py          run on a folder of applications
api/              backend service (FastAPI on Koyeb): review (upload), stream (SSE), runs
ui/               Next.js + React + TS on Vercel: Dropzone · LoopView · DecisionPanel · Shortlist
evals/            gold examples + calibration       tests/  E2E + unit + telemetry
data/             sample applications (incl. fraud case) + gold set
```

### The loop
For each applicant (under the active RoleProfile):
1. **Verify credential** — the harness calls the tool; the worker never touches it.
2. **Hard-gate** on the result: valid → eligible; expired/not-found → ineligible (+alarm);
   name-mismatch → escalate (fraud, critical alarm); tool unavailable/ambiguous → escalate.
3. If eligible, **worker proposes** an evaluation (scores + cited evidence + recommendation).
4. **Guardrails + Checkpoint gate** the proposal.
5. On **fail**, the specific failure is returned and the **worker revises that same applicant**
   (bounded retries). Pass → persist. Retries exhausted → escalate.
6. **Rank deterministically** (harness sorts; the LLM does not).

Every step emits a Phoenix span AND a `LoopEvent` for the dashboard. Alarms bridge into both.

### Role Profiles — the versatility mechanism
```
RoleProfile = {
  rubric:           scoring criteria for this role,
  required_creds:   [TEA cert]   |   [Food Handler card (+ CFM if manager)],
  verifier:         TEACredentialVerifier  |  FoodHandlerVerifier,
  guardrail_config: declared rules for this role,
}
```
The harness loads a profile and runs unchanged. Swapping the profile retargets the whole
harness from "teacher" to "cafeteria worker." Built in from Phase 1 (cheap — the harness
already takes a rubric + verifier); the second profile is the stretch.

**Three real-world verification topologies, one interface:**
| Role | Topology | Verifier strategy |
|---|---|---|
| Teacher (TEA) | single state registry | one authoritative lookup |
| Food handler (DSHS) | federated, many issuers | router → correct issuer's verify endpoint + DSHS-accredited-issuer allowlist + document fallback |

### Observability + UI: one instrumentation, two audiences
- **Phoenix** via OTel/OpenLLMetry — deep trace for debugging (prompts, tokens, cost, latency).
- **Dashboard** via the in-process event bus → SSE — live, human-readable view for the demo.

---

## UI — "EducationApplicantVerifier Dashboard" (deployed harness URL on Vercel)
**No sign-in.** Loads straight to the dashboard.
1. **Dropzone** — drag a resume (PDF/text) / pick a sample → starts a single-applicant run.
2. **Live Loop View** — pipeline (Material In → Worker → Guardrails → Checkpoint → Decision)
   lights up stage by stage: watch Attempt 1 fail → Attempt 2 pass, the credential lookup
   resolve, alarms fire in real time.
3. **Decision / "Why" panel** — Accepted / Rejected / Escalated with credential status,
   per-criterion scores + cited evidence, the failures caught, alarms (type·severity·action),
   attempt history, link to the Phoenix trace.
4. **Session Shortlist** (optional) — ranked list of resumes dropped this session.

**Backend (Koyeb):** `POST /api/review` (upload) · `GET /api/review/{id}/stream` (SSE) ·
`GET /api/runs/{id}` (final result). UI on Vercel calls it.

**Note:** raw PDF → `Application` schema is the Material In pillar's job. Demo supports drop-in
sample applicants + best-effort PDF parse so it never stalls.

---

## Phases

Each phase is built **test-first**; it is not done until its *Exit* tests are green and the full
suite still passes.

### Walking skeleton (fakes — fast path to a working harness)
- **Phase 0 — Setup** (~15m): requirements (pytest, opentelemetry-sdk, traceloop/openllmetry,
  arize-phoenix, fastapi, uvicorn), scaffold, `phoenix serve`. *Exit:* `pytest` runs; Phoenix loads.
- **Phase 1 — Types, interfaces, alarms, RoleProfile** (~35m): `types.py`, `alarms.py`
  (declared catalog), `profiles.py` (RoleProfile + default teacher profile). *Exit:* alarm-catalog
  test green.
- **Phase 2 — Observability** (~30m): `observability.py` (OTel → Phoenix, alarm→span bridge,
  in-memory exporter for tests), `events.py` bus. *Exit:* span in Phoenix; exporter test green.
- **Phase 3 — Fakes** (~30m): `FakeWorker` (over-claims on attempt 1, corrects on feedback),
  `FakeCredentialVerifier` (valid / expired / not-found / mismatch=fraud / unavailable; counts
  calls). *Exit:* worker revises-on-feedback test green.
- **Phase 4 — The four pillars** (~60m): `material.py`, `guardrails.py`, `checkpoints.py`.
  *Exit:* per-pillar unit tests green.
- **Phase 5 — Harness loop + store** (~45m): `harness.py` (instrumented; runs a RoleProfile),
  `store.py` (persist per-applicant; replay skips completed work). *Exit:* runs without error;
  store/replay test green.
- **Phase 6 — E2E test green (headline)** (~45m) ★: 6 sample educators — valid ranks top ·
  hallucination took 2 attempts · expired & not-found → ineligible + alarms · mismatch →
  `CERT_MISMATCH` + escalation · unavailable → escalate · replay skips rework · telemetry
  recorded. *Exit:* `pytest` fully green.
- **Phase 7 — CLI + run with fakes** (~30m) ★ **CORE MVP**: `cli.py` on `data/`; traces in
  Phoenix. *Exit:* complete harness on fakes hitting every MUST/SHOULD; full suite green.

### UI
- **Phase 8 — Backend API + live event stream** (~45m): FastAPI on Koyeb — upload, SSE wired to
  the event bus, results; single-applicant runs. *Exit:* API test green; curl upload → SSE events.
- **Phase 9 — Frontend dashboard** (~90m) ★ **DASHBOARD MVP**: Next.js — Dropzone, live LoopView,
  Decision/Why panel, optional Shortlist; no auth. *Exit:* drop a sample → watch loop → see why.

### Fill in the real parts
- **Phase 10 — Real Claude worker** (~45m): `LLMWorker` behind the interface; OpenLLMetry
  captures prompts/tokens/cost into Phoenix. Keep `FakeWorker` for the **live worker-swap bonus**.
  *Exit:* E2E passes with `LLMWorker` on a seeded input.
- **Phase 11 — Real TEA verifier** (~60m, riskiest): `TEACredentialVerifier` against ECOS
  VirtCert, behind the interface, with caching + `TOOL_UNAVAILABLE` fallback; live-or-fixture
  mode. *Exit:* a real cert verifies; tool-down path escalates (fixture test green).
- **Phase 12 — Gold-set evals / calibration** (~30m): `evals/` over ~10 gold educators; assert
  they clear bar; drift → `CALIBRATION_DRIFT`; pass-rate metric into Phoenix. *Exit:* green.

### Ship
- **Phase 13 — Deploy** (~45m): backend → **Koyeb**, frontend → **Vercel** → **deployed URL**.
  Phoenix local/sidecar. *Exit:* deployed URL runs a sample input end to end.
- **Phase 14 — Deliverables & polish** (~45m): `HARNESS.md`, README, 5-min demo video (loop in
  the dashboard + the fraud catch + a live worker swap), line up the **real input** (a real
  educator req + a few real applications / cert numbers). Regenerate the planning PDF under the
  new name if desired. *Exit:* all deliverables submitted; full suite green.

### Stretch (only after CORE MVP + Dashboard are green; off the critical path)
- **Stretch S1 — Food-handling Role Profile** (~60–90m): `FoodHandlerVerifier` (issuer router +
  **DSHS-accredited-issuer allowlist** check + document fallback), food alarm types
  (`FOOD_HANDLER_MISSING`, `FOOD_HANDLER_EXPIRED`, `FOOD_HANDLER_UNACCREDITED_ISSUER`,
  `CFM_REQUIRED_MISSING`, `ISSUER_UNVERIFIABLE → escalate`), a cafeteria-worker rubric, sample
  food-service applicants. **Demo:** run the Teacher profile, then swap to the Cafeteria profile
  through the *same harness*. *Exit:* food-handling E2E green; profile swap shown in the dashboard.

---

## Requirement coverage
| Requirement | Phase |
|---|---|
| MUST four pillars, separate from worker | 4 |
| MUST behavior changes on guardrail/checkpoint feedback | 5–6 (correction loop) |
| MUST guardrails declared / checkpoints explicit pass/fail | 4 |
| MUST alarms structured (type·severity·context·action) | 1 |
| MUST runs on real input at demo | 11 + 14 |
| MUST HARNESS.md | 14 |
| SHOULD swappable agent interface | 3 / 10 |
| SHOULD checkpoints persisted + replayable | 5 |
| SHOULD human-in-the-loop escalation | 5 |
| BONUS swap 2nd worker live | 10 / 14 |
| Observability (Phoenix / OTel) | 2 (bridged throughout) |
| UI dashboard (deployed) | 8–9, 13 |
| Versatility (swap domains via RoleProfile) | 1 + Stretch S1 |
| Everything verified working (TDD) | all phases + green-before-submission gate |

---

## Risks & mitigations
- **TEA site form/rate-limits/changes** → adapter behind interface; cache; live-or-fixture mode;
  `TOOL_UNAVAILABLE` escalates.
- **Food handling has no central registry** (federated issuers) → router + DSHS-accredited
  allowlist + document fallback; keep it a stretch.
- **Koyeb free-tier limits** → backend is small; switch to Cloud Run if testing needs it.
- **Time** → Phases 0–7 (CORE MVP) and 8–9 (DASHBOARD MVP) are priority; real Claude/TEA, evals,
  deploy follow; food handling is pure stretch. Fakes make every prior phase demoable and tested.
- **Real input requirement** → only the user can supply a real educator req + applications +
  TEA cert numbers; line up before the demo.

## One thing only the user can do
Provide a **real input** for the demo: a real educator role + one or two real applications, and
real TEA certificate numbers (public lookups) — so Phase 11/14 runs on genuine data.
