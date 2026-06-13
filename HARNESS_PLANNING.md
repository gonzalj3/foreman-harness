# Harness Planning Document — "Foreman"

**A harness that supervises an autonomous hiring & recruitment-marketing agent.**
The agent only *proposes* the next step; the harness validates, executes, evaluates, monitors, and persists every action around it. Swap the agent and the constraints still hold.

- **Domain (the worker's job):** run a real job req end-to-end — draft the JD, plan & launch an ad campaign, ingest and score resumes, book interviews — under a fixed budget and legal constraints.
- **What we're graded on (the harness):** the four pillars below, each a distinct module the worker cannot bypass.

## Core architecture — separation of worker and harness

The worker is a thin, swappable interface: `proposeStep(stage, context) → Action`. It has **no I/O and no authority** — it only suggests. The harness owns the loop:

```
real input ──▶ [Material In] ──▶ context ──▶ ( WORKER.proposeStep ) ──▶ Action
                                                                          │
                          ┌───────────────────────────────────────────────┘
                          ▼
                   [Guardrails] ──fail──▶ block + raise Alarm + (HITL escalate)
                          │ pass
                          ▼
                   [Material Out] ── execute I/O (ad stub, calendar, ATS) ──▶ result
                          ▼
                   [Checkpoint] ──fail──▶ retry / raise Alarm / escalate
                          │ pass
                          ▼
                   [Persist checkpoint] ──▶ next stage (replayable from here)
        [Alarms] monitor the whole loop and emit structured events throughout.
```

## The four pillars

| Pillar | In Foreman | Demo moment |
|---|---|---|
| **Guardrails** *(declared in `guardrails.yaml`)* | Budget cap + per-channel caps; **EEOC/bias** filter on all copy & screening criteria; PII-redaction before text leaves the boundary; action limits (max N outreach, no double-book; scope = this req only). | Agent writes "young, energetic grad" → guardrail blocks the JD before it ships. |
| **Checkpoints** *(explicit pass/fail, persisted)* | Per stage: **JD** (required fields, reading level, salary-range-if-required, bias-scan) · **Campaign** (allocations ≤ budget, projected CPA ≤ target) · **Scoring** (every candidate has score+justification, valid schema, calibrated — not all-10s) · **Schedule** (no conflict, in-hours, above bar). | Replay the run from the "Scoring" checkpoint without re-drafting the JD or re-running ads. |
| **Material handling** *(clean in/out interfaces)* | **In:** normalize a job req + a folder/inbox of heterogeneous resumes (PDF/text) → one canonical schema. **Out:** typed adapters to a **simulated ad market** (fast-clock impressions→clicks→applications), calendar, and a candidate store. Worker never touches raw PDFs or raw APIs. | Drop a messy real PDF resume in; the worker sees clean typed fields. |
| **Alarms** *(structured: type, severity, context, action)* | `BIAS_DETECTED`(critical→block+HITL) · `BUDGET_OVERRUN`(high→pause+HITL) · `PII_LEAK_RISK`(high→block) · `LOW_APPLICANT_FLOW`(med→suggest reallocation) · `SCORE_ANOMALY`(med→re-run stricter) · `CALENDAR_CONFLICT`(low→pick alt slot). | Push spend over cap → `BUDGET_OVERRUN` fires with severity + recommended action, loop pauses. |

## The two coupled loops (the domain logic the harness governs)

1. **Acquisition loop** — launch/adjust ads on the simulated market → applications arrive → optimize cost-per-*qualified*-applicant.
2. **Selection loop** — score incoming resumes against the rubric → schedule interviews → fill slots.

They share one budget; the agent trades "buy more applicants" vs. "stop, I have enough." Foreman enforces the shared cap across both via the budget guardrail + `BUDGET_OVERRUN` alarm.

## "Should" requirements (built in, not bolted on)

- **Swappable agent:** worker behind `Worker` interface; harness has zero agent-specific code. *Bonus:* swap a second worker (e.g. different model) live in the demo to prove portability.
- **Persistence / replay:** every checkpoint result is written to a run store; any stage replays forward without re-running prior stages.
- **Human-in-the-loop:** any guardrail block or alarm of severity ≥ high **stops and asks** rather than guessing.

## Stack, deploy, and the real input *(to confirm)*

- **Stack:** _[TypeScript/Node or Python — TODO]_; harness as a small framework + web UI to drive a run and watch checkpoints/alarms live. Deployed URL for Saturday.
- **Real input (MUST, demo-time):** a **real open req from Salinas Software LLC** + **~10–20 real resumes** (network / a real posting). _Need to line these up before the demo._
- **Simulated ad market:** local stub on an accelerated clock — no gated API, no real money/PII, and the optimization loop is visible on stage.

## Top risks

- **Scope:** two loops + simulated market + four pillars in 24h. Mitigation: pillars first (they're the grade), then one loop end-to-end, then the second loop if time.
- **Pillar/worker separation must be *visible* in code** — keep each pillar a named module the worker calls into, never prompt-embedded logic.
