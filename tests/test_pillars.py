"""Per-pillar unit tests: guardrails, checkpoints, worker behavior, alarm catalog."""
from education_applicant_verifier import alarms, checkpoints, guardrails
from education_applicant_verifier.alarms import AlarmType
from education_applicant_verifier.types import (
    Application, CredentialResult, CredStatus, CriterionScore, Failure, Proposal,
)
from education_applicant_verifier.worker import FakeWorker


def app(**kw):
    base = dict(id="x", name="X", role="teacher", cert_id="TX-1",
                claimed_experience_years=3, document_experience_years=3, narrative="ok")
    base.update(kw)
    return Application(**base)


def proposal(**kw):
    base = dict(applicant_id="x", overall_score=7,
                criteria=[CriterionScore("experience", 7, "3 years stated")],
                recommendation="advance", claims={"experience_years": 3}, rationale="solid candidate")
    base.update(kw)
    return Proposal(**base)


# ---- alarms ----

def test_alarm_catalog_has_severity_and_action():
    a = alarms.raise_alarm(AlarmType.CERT_MISMATCH, "x", {"k": "v"})
    assert a.severity.value == "critical"
    assert a.recommended_action
    assert a.context == {"k": "v"}


# ---- guardrails ----

def test_guardrail_flags_ungrounded_claim():
    r = guardrails.check(proposal(claims={"experience_years": 9}), app(document_experience_years=2))
    assert not r.passed
    assert any(f.code == "UNGROUNDED_CLAIM" for f in r.failures)
    assert any(a.type == AlarmType.HALLUCINATED_QUALIFICATION for a in r.alarms)


def test_guardrail_flags_biased_language():
    r = guardrails.check(proposal(rationale="great young energetic candidate"), app())
    assert not r.passed
    assert any(a.type == AlarmType.BIAS_DETECTED for a in r.alarms)


def test_guardrail_passes_clean_proposal():
    assert guardrails.check(proposal(), app()).passed


# ---- checkpoints ----

def test_checkpoint_requires_citation():
    r = checkpoints.check_evaluation(
        proposal(criteria=[CriterionScore("experience", 7, "   ")]), app())
    assert not r.passed
    assert any(f.code == "MISSING_CITATION" for f in r.failures)


def test_credential_gate_maps_statuses():
    assert checkpoints.credential_gate(app(), CredentialResult("TX-1", CredStatus.VALID))[0] == "eligible"
    assert checkpoints.credential_gate(app(), CredentialResult("TX-1", CredStatus.EXPIRED))[0] == "ineligible"
    assert checkpoints.credential_gate(app(), CredentialResult("TX-1", CredStatus.NOT_FOUND))[0] == "ineligible"
    assert checkpoints.credential_gate(app(), CredentialResult("TX-1", CredStatus.MISMATCH))[0] == "escalate"
    assert checkpoints.credential_gate(app(), CredentialResult("TX-1", CredStatus.UNAVAILABLE))[0] == "escalate"


# ---- worker correction behavior ----

def test_worker_revises_when_experience_flagged():
    w = FakeWorker()
    a = app(claimed_experience_years=10, document_experience_years=2)
    first = w.propose(a, ["experience"], [])
    assert first.claims["experience_years"] == 10
    feedback = [Failure("UNGROUNDED_CLAIM", "too high", field="experience_years")]
    second = w.propose(a, ["experience"], feedback)
    assert second.claims["experience_years"] == 2
