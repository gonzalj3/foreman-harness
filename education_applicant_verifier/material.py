"""Pillar 1 — Material handling.

Clean I/O: heterogeneous applications in -> canonical Application schema; results
out -> plain JSON-able dicts. The worker never touches raw files or enums.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .types import (
    Application, Alarm, CredentialResult, Escalation, Evaluation, Proposal, RunResult,
)


def from_dict(d: dict) -> Application:
    return Application(
        id=d["id"],
        name=d["name"],
        role=d.get("role", "teacher"),
        cert_id=d.get("cert_id"),
        claimed_experience_years=int(d.get("claimed_experience_years", 0)),
        document_experience_years=int(d.get("document_experience_years", 0)),
        narrative=d.get("narrative", ""),
        metadata=d.get("metadata", {}),
    )


def load_applications(path: str) -> list[Application]:
    with open(path) as f:
        data = json.load(f)
    return [from_dict(d) for d in data]


def _alarm(a: Alarm) -> dict:
    return {
        "type": a.type, "severity": a.severity.value, "applicant_id": a.applicant_id,
        "context": a.context, "recommended_action": a.recommended_action,
    }


def _credential(c: CredentialResult) -> dict:
    return {
        "cert_id": c.cert_id, "status": c.status.value, "holder_name": c.holder_name,
        "cert_type": c.cert_type, "expires": c.expires,
    }


def _proposal(p: Proposal | None) -> dict | None:
    if p is None:
        return None
    return {
        "overall_score": p.overall_score, "recommendation": p.recommendation,
        "rationale": p.rationale, "claims": p.claims,
        "criteria": [{"name": c.name, "score": c.score, "evidence": c.evidence} for c in p.criteria],
    }


def _evaluation(e: Evaluation) -> dict:
    return {
        "applicant_id": e.applicant_id, "name": e.name, "status": e.status,
        "eligible": e.eligible, "accepted": e.accepted, "overall_score": e.overall_score,
        "attempts": e.attempts, "credential": _credential(e.credential),
        "proposal": _proposal(e.proposal),
        "failures": [asdict(f) for f in e.failures],
        "alarms": [_alarm(a) for a in e.alarms],
    }


def _escalation(e: Escalation) -> dict:
    return {
        "applicant_id": e.applicant_id, "name": e.name, "reason": e.reason,
        "failures": [asdict(f) for f in e.failures],
        "alarms": [_alarm(a) for a in e.alarms],
    }


def render(result: RunResult) -> dict[str, Any]:
    return {
        "ranking": [_evaluation(e) for e in result.ranking],
        "ineligible": [_evaluation(e) for e in result.ineligible],
        "escalations": [_escalation(e) for e in result.escalations],
        "alarms": [_alarm(a) for a in result.alarms],
    }
