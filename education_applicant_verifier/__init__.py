"""EducationApplicantVerifier — a harness that supervises a swappable AI worker
reviewing education-sector applications, with credential verification against
external authorities.

The worker only *proposes* an evaluation; the harness validates it, gates it,
alarms on problems, persists each step, and ranks — so constraint-handling is
invisible to the agent.

The four pillars are separate, importable modules:
    material    — clean I/O (applications in, ranked decisions out)
    guardrails  — declared rules that block bad worker output
    checkpoints — explicit pass/fail gates (incl. the credential hard-gate)
    alarms      — structured, named events with severity + recommended action

The worker (the AI), the credential verifier (the tool), and the observability
backend are all swappable behind interfaces and never imported by the harness
directly. A RoleProfile bundles the rubric + required credentials + verifier +
guardrail config, so the same harness retargets from "teacher" to "cafeteria
worker" by swapping the profile.

Built test-first (TDD, E2E-first): every component is covered by tests, and a
green `pytest` suite is the definition of ship-ready.
"""
