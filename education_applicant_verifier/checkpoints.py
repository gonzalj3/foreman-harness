"""Pillar 3 — Checkpoints.

Explicit pass/fail gates on the worker's output, plus the credential hard-gate
that uses the verifier (tool) result to decide eligibility. Checkpoints have
explicit criteria and return structured failures.
"""
from __future__ import annotations

from . import alarms
from .alarms import AlarmType
from .types import Application, CheckResult, CredentialResult, CredStatus, Failure, Proposal


def check_evaluation(proposal: Proposal, application: Application) -> CheckResult:
    """Schema + citation + recommendation validity for a single evaluation."""
    failures: list[Failure] = []
    raised: list = []
    checks: list[dict] = []

    # schema / criteria present
    checks.append({
        "name": "evaluation has scored criteria",
        "passed": bool(proposal.criteria),
        "detail": f"{len(proposal.criteria)} criteria scored",
    })
    if not proposal.criteria:
        failures.append(Failure("EMPTY_EVALUATION", "no criteria were scored"))

    # every criterion cites evidence
    uncited = [c.name for c in proposal.criteria if not (c.evidence or "").strip()]
    checks.append({
        "name": "every criterion cites evidence",
        "passed": not uncited,
        "detail": ("missing on: " + ", ".join(uncited)) if uncited
                  else f"all {len(proposal.criteria)} criteria cite evidence",
    })
    for name in uncited:
        failures.append(Failure("MISSING_CITATION", f"criterion '{name}' has no cited evidence", name))
        raised.append(alarms.raise_alarm(AlarmType.MISSING_CITATION, application.id, {"criterion": name}))

    # criterion scores in range
    oor = [c.name for c in proposal.criteria if not (0 <= c.score <= 10)]
    checks.append({
        "name": "criterion scores within 0-10",
        "passed": not oor,
        "detail": ("out of range: " + ", ".join(oor)) if oor else "all criterion scores in range",
    })
    for name in oor:
        c = next(c for c in proposal.criteria if c.name == name)
        failures.append(Failure("CRITERION_OUT_OF_RANGE", f"criterion '{name}' score {c.score} outside 0-10", name))

    # recommendation valid
    rec_ok = proposal.recommendation in ("advance", "reject")
    checks.append({
        "name": "recommendation is advance/reject",
        "passed": rec_ok,
        "detail": f"recommendation = {proposal.recommendation}",
    })
    if not rec_ok:
        failures.append(Failure(
            "BAD_RECOMMENDATION", f"recommendation '{proposal.recommendation}' is not advance/reject"))

    return CheckResult(passed=not failures, failures=failures, alarms=raised, checks=checks)


def credential_gate(application: Application, cred: CredentialResult):
    """The hard-requirement gate. Returns (decision, alarms, reason).

    decision in {"eligible", "ineligible", "escalate"}.
    """
    raised: list = []

    if cred.status == CredStatus.VALID:
        return "eligible", raised, None

    if cred.status == CredStatus.EXPIRED:
        raised.append(alarms.raise_alarm(
            AlarmType.CERT_EXPIRED, application.id, {"cert_id": cred.cert_id, "expires": cred.expires}))
        return "ineligible", raised, "certificate has expired"

    if cred.status == CredStatus.NOT_FOUND:
        raised.append(alarms.raise_alarm(
            AlarmType.CERT_NOT_FOUND, application.id, {"cert_id": cred.cert_id}))
        return "ineligible", raised, "no valid certificate found"

    if cred.status == CredStatus.MISMATCH:
        raised.append(alarms.raise_alarm(
            AlarmType.CERT_MISMATCH, application.id,
            {"cert_id": cred.cert_id, "holder": cred.holder_name, "applicant": application.name}))
        return "escalate", raised, "certificate holder does not match applicant (possible fraud)"

    # UNAVAILABLE / ambiguous
    raised.append(alarms.raise_alarm(
        AlarmType.TOOL_UNAVAILABLE, application.id, {"cert_id": cred.cert_id}))
    return "escalate", raised, "credential verification unavailable"
