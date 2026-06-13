"""Pillar 4 — Alarms.

A *declared* catalog of named alarm types, each mapped to a severity and a
recommended action. Guardrails and checkpoints raise alarms via `raise_alarm`,
so every alarm in the system is structured and named (never ad-hoc).
"""
from __future__ import annotations

from .types import Alarm, Severity


class AlarmType:
    HALLUCINATED_QUALIFICATION = "HALLUCINATED_QUALIFICATION"
    BIAS_DETECTED = "BIAS_DETECTED"
    PII_LEAK_RISK = "PII_LEAK_RISK"
    SCORE_OUT_OF_RANGE = "SCORE_OUT_OF_RANGE"
    MISSING_CITATION = "MISSING_CITATION"
    CERT_EXPIRED = "CERT_EXPIRED"
    CERT_NOT_FOUND = "CERT_NOT_FOUND"
    CERT_MISMATCH = "CERT_MISMATCH"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    RETRY_BUDGET_EXCEEDED = "RETRY_BUDGET_EXCEEDED"


# type -> (severity, recommended_action)
CATALOG: dict[str, tuple[Severity, str]] = {
    AlarmType.HALLUCINATED_QUALIFICATION: (
        Severity.HIGH, "Block output; require re-evaluation grounded only in the document"),
    AlarmType.BIAS_DETECTED: (
        Severity.CRITICAL, "Block; rewrite without protected-class reasoning; flag for human review"),
    AlarmType.PII_LEAK_RISK: (
        Severity.HIGH, "Redact PII before it leaves the boundary"),
    AlarmType.SCORE_OUT_OF_RANGE: (
        Severity.MEDIUM, "Reject evaluation; score outside 0-10"),
    AlarmType.MISSING_CITATION: (
        Severity.MEDIUM, "Reject evaluation; require cited evidence for each criterion"),
    AlarmType.CERT_EXPIRED: (
        Severity.HIGH, "Mark ineligible; notify applicant the certificate has expired"),
    AlarmType.CERT_NOT_FOUND: (
        Severity.HIGH, "Mark ineligible; no valid certificate on record"),
    AlarmType.CERT_MISMATCH: (
        Severity.CRITICAL, "Escalate to human; certificate holder does not match applicant (possible fraud)"),
    AlarmType.TOOL_UNAVAILABLE: (
        Severity.MEDIUM, "Escalate to human; could not verify credential"),
    AlarmType.RETRY_BUDGET_EXCEEDED: (
        Severity.HIGH, "Escalate to human; worker could not produce a valid evaluation"),
}


def raise_alarm(alarm_type: str, applicant_id: str | None, context: dict | None = None) -> Alarm:
    severity, action = CATALOG[alarm_type]
    return Alarm(
        type=alarm_type,
        severity=severity,
        applicant_id=applicant_id,
        context=context or {},
        recommended_action=action,
    )
