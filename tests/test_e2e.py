"""Headline end-to-end test — the whole harness over the 6 sample applicants,
driven by a REAL worker class (DeepSeekWorker) with the model's network mocked.
Credential statuses come from FakeCredentialVerifier (a tool double).
"""
import os

from education_applicant_verifier.events import EventBus
from education_applicant_verifier.harness import Harness
from education_applicant_verifier.material import load_applications
from education_applicant_verifier.observability import Tracer
from education_applicant_verifier.profiles import teacher_profile
from education_applicant_verifier.store import RunStore
from education_applicant_verifier.verifier import FakeCredentialVerifier
from education_applicant_verifier.worker import DeepSeekWorker
from support import clean_eval, patch_openai_model, revise_eval

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "applications.json")


def build(monkeypatch, content_fn=clean_eval):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")  # presence only; network is mocked
    patch_openai_model(monkeypatch, content_fn)
    apps = load_applications(DATA)
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    verifier = FakeCredentialVerifier()
    worker = DeepSeekWorker()
    harness = Harness(teacher_profile(verifier), worker, tracer=Tracer(bus))
    return apps, harness, verifier, worker, events


def test_ranking_and_acceptance(monkeypatch):
    apps, h, *_ = build(monkeypatch)
    result = h.run(apps)
    assert {e.applicant_id for e in result.ranking} == {"maria", "james"}
    assert all(e.accepted for e in result.ranking)


def test_ineligible_hard_gate(monkeypatch):
    apps, h, *_ = build(monkeypatch)
    result = h.run(apps)
    assert {e.applicant_id for e in result.ineligible} == {"robert", "sarah"}
    types = {a.type for e in result.ineligible for a in e.alarms}
    assert "CERT_EXPIRED" in types and "CERT_NOT_FOUND" in types


def test_fraud_and_unavailable_escalate(monkeypatch):
    apps, h, *_ = build(monkeypatch)
    result = h.run(apps)
    assert {e.applicant_id for e in result.escalations} == {"evan", "nina"}
    mismatch = [a for a in result.alarms if a.type == "CERT_MISMATCH"]
    assert mismatch and mismatch[0].severity.value == "critical"
    assert any(a.type == "TOOL_UNAVAILABLE" for a in result.alarms)


def test_correction_loop_revises_on_feedback(monkeypatch):
    apps, h, *_ = build(monkeypatch, revise_eval)
    result = h.run(apps)
    by_id = {e.applicant_id: e for e in result.ranking}
    # first attempt omitted a citation -> checkpoint fail -> worker revised
    assert by_id["maria"].attempts == 2
    assert any(a.type == "MISSING_CITATION" for a in result.alarms)


def test_replay_skips_rework(monkeypatch):
    apps, h, verifier, worker, _ = build(monkeypatch)
    h.store = RunStore()
    h.run(apps)
    v_calls, w_calls = verifier.calls, worker.calls
    result2 = h.run(apps)  # all cached -> no new verify or model calls
    assert verifier.calls == v_calls and worker.calls == w_calls
    assert {e.applicant_id for e in result2.ranking} == {"maria", "james"}


def test_telemetry_recorded(monkeypatch):
    apps, h, _, _, events = build(monkeypatch)
    h.run(apps)
    alarm_events = [e for e in events if e.kind == "alarm"]
    assert any(e.data.get("type") == "CERT_MISMATCH" for e in alarm_events)
    assert sum(1 for e in events if e.kind == "decision") == 4  # 2 scored + 2 ineligible
