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

    if not proposal.criteria:
        failures.append(Failure("EMPTY_EVALUATION", "no criteria were scored"))

    for c in proposal.criteria:
        if not (0 <= c.score <= 10):
            failures.append(Failure(
                "CRITERION_OUT_OF_RANGE", f"criterion '{c.name}' score {c.score} outside 0-10", c.name))
        if not c.evidence or not c.evidence.strip():
            failures.append(Failure(
                "MISSING_CITATION", f"criterion '{c.name}' has no cited evidence", c.name))
            raised.append(alarms.raise_alarm(AlarmType.MISSING_CITATION, application.id, {"criterion": c.name}))

    if proposal.recommendation not in ("advance", "reject"):
        failures.append(Failure(
            "BAD_RECOMMENDATION", f"recommendation '{proposal.recommendation}' is not advance/reject"))

    return CheckResult(passed=not failures, failures=failures, alarms=raised)


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
