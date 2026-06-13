"""Domain types and the two swappable interfaces (Worker, CredentialVerifier).

These are plain dataclasses so the harness logic is explicit and easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CredStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    MISMATCH = "mismatch"        # cert exists but belongs to a different name -> fraud signal
    UNAVAILABLE = "unavailable"  # tool down / timeout / ambiguous -> escalate


# ---- Material handling: input + output ----

@dataclass
class Application:
    id: str
    name: str
    role: str
    cert_id: Optional[str]
    claimed_experience_years: int      # what the applicant asserts
    document_experience_years: int     # what the document actually supports
    narrative: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CredentialResult:
    cert_id: Optional[str]
    status: CredStatus
    holder_name: Optional[str] = None
    cert_type: Optional[str] = None
    expires: Optional[str] = None
    certifications: list[str] = field(default_factory=list)   # certified subject areas (e.g. Mathematics)
    grade_bands: list[str] = field(default_factory=list)      # certified grade bands (e.g. 4-8)
    raw: dict = field(default_factory=dict)


# ---- Worker output ----

@dataclass
class CriterionScore:
    name: str
    score: int          # 0..10
    evidence: str       # cited support from the application


@dataclass
class Proposal:
    applicant_id: str
    overall_score: int
    criteria: list[CriterionScore]
    recommendation: str            # "advance" | "reject"
    claims: dict                   # structured claims the worker asserts, e.g. {"experience_years": 5}
    rationale: str


# ---- Checker output ----

@dataclass
class Failure:
    code: str
    message: str
    field: Optional[str] = None


@dataclass
class Alarm:
    type: str
    severity: Severity
    applicant_id: Optional[str]
    context: dict
    recommended_action: str


@dataclass
class CheckResult:
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)


# ---- Per-applicant results ----

@dataclass
class Evaluation:
    applicant_id: str
    name: str
    status: str                 # "scored" | "ineligible"
    eligible: bool
    accepted: bool
    overall_score: int
    attempts: int
    proposal: Optional[Proposal]
    credential: CredentialResult
    failures: list[Failure] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)


@dataclass
class Escalation:
    applicant_id: str
    name: str
    reason: str
    failures: list[Failure] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)


@dataclass
class RunResult:
    ranking: list[Evaluation] = field(default_factory=list)
    ineligible: list[Evaluation] = field(default_factory=list)
    escalations: list[Escalation] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)


# ---- Swappable interfaces (the harness depends only on these) ----

class Worker(Protocol):
    name: str

    def propose(
        self, application: Application, rubric: list[str], prior_failures: list[Failure]
    ) -> Proposal: ...


class CredentialVerifier(Protocol):
    name: str

    def verify(self, cert_id: Optional[str], applicant_name: str) -> CredentialResult: ...
