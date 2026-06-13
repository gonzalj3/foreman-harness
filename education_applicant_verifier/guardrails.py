"""Pillar 2 — Guardrails.

Declared rules that block bad worker output. These run on the worker's proposal
*before* it is accepted; failures are returned so the worker can revise. The
rules are explicit here (not buried in a prompt) — that is what "declared, not
implicit" means.
"""
from __future__ import annotations

from . import alarms
from .alarms import AlarmType
from .types import Application, CheckResult, Failure, Proposal


# Declared protected-class / age-coded language that must never drive a decision.
BANNED_TERMS = [
    "young", "energetic", "fresh out of", "digital native", "recent grad",
    "old", "elderly", "overqualified for his age", "cultural fit",
]


def check(proposal: Proposal, application: Application, config: dict | None = None) -> CheckResult:
    failures: list[Failure] = []
    raised: list = []

    # 1. Grounding: a claimed qualification may not exceed what the document supports.
    claimed_years = proposal.claims.get("experience_years")
    if claimed_years is not None and claimed_years > application.document_experience_years:
        failures.append(Failure(
            "UNGROUNDED_CLAIM",
            f"Claimed {claimed_years} years of experience but the application supports "
            f"{application.document_experience_years}",
            field="experience_years",
        ))
        raised.append(alarms.raise_alarm(
            AlarmType.HALLUCINATED_QUALIFICATION, application.id,
            {"claimed": claimed_years, "supported": application.document_experience_years},
        ))

    # 2. No protected-class / biased language anywhere in the evaluation.
    text = " ".join([proposal.rationale] + [c.evidence for c in proposal.criteria]).lower()
    hits = [t for t in BANNED_TERMS if t in text]
    if hits:
        failures.append(Failure("BIASED_LANGUAGE", f"Protected-class / biased language: {hits}"))
        raised.append(alarms.raise_alarm(AlarmType.BIAS_DETECTED, application.id, {"terms": hits}))

    # 3. Score must be in range.
    if not (0 <= proposal.overall_score <= 10):
        failures.append(Failure(
            "SCORE_OUT_OF_RANGE", f"Overall score {proposal.overall_score} is outside 0-10"))
        raised.append(alarms.raise_alarm(
            AlarmType.SCORE_OUT_OF_RANGE, application.id, {"score": proposal.overall_score}))

    return CheckResult(passed=not failures, failures=failures, alarms=raised)
