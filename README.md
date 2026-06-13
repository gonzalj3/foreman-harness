# EducationApplicantVerifier

A **harness** that supervises a swappable AI worker reviewing education-sector
applications. The worker only *proposes* an evaluation; the harness verifies the
applicant's credential (e.g. Texas TEA educator certificate), enforces declared
guardrails, gates every output through pass/fail checkpoints, raises structured
alarms, persists each step, and ranks — so constraint-handling is invisible to
the agent.

Built test-first (TDD). See [`PLAN.md`](PLAN.md) for the full plan and phases.

## The four pillars (each a separate module, separate from the worker)
- `material.py` — clean I/O: applications in → schema; ranked decisions out
- `guardrails.py` — declared rules (grounding, bias, score range)
- `checkpoints.py` — explicit pass/fail gates + the credential hard-gate
- `alarms.py` — structured, named alarms (type · severity · context · action)

The **worker** (`worker.py`) and **credential verifier** (`verifier.py`) are
swappable behind protocols in `types.py`. A **RoleProfile** (`profiles.py`)
bundles the rubric + verifier + config so the same harness retargets to other
roles (e.g. food-service staff).

## The loop
verify credential → hard-gate → worker proposes → guardrails + checkpoint gate →
on fail, return the specific failure and the worker **revises that applicant**
(bounded) → pass = persist, else escalate to a human → rank deterministically.

## Run locally
```bash
pip install -r requirements-dev.txt
pytest                                   # full suite (offline, deterministic)
python -m education_applicant_verifier.cli data/        # run the harness on samples
uvicorn education_applicant_verifier.server:app --reload  # dashboard at http://localhost:8000
```

## Deploy (Koyeb)
This is a single service (API + dashboard). Deploy from GitHub:

1. Create a free Koyeb account, **Create Service → GitHub →** this repo.
2. Builder: **Dockerfile** (or Buildpack — it will use the `Procfile`).
3. Koyeb sets `$PORT`; the app binds to it automatically. No env vars required for the demo.
4. Deploy → you get a public URL serving the dashboard.

Frontend can later move to **Vercel** (Next.js) calling this backend; Cloud Run
is the backend fallback if Koyeb limits bite.

## Status
CORE MVP (harness + four pillars + tool + correction loop + escalation + alarms)
and a deployable dashboard, all green under `pytest`. Real Claude worker, real
TEA verifier, Phoenix/OTel observability, and the food-handling RoleProfile are
the next phases in `PLAN.md`.
