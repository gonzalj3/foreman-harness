"""Headline end-to-end test — the contract the whole harness serves.

Runs the full harness over the 6 sample educators with fakes and asserts the
decisions, alarms, escalations, the correction loop, replay, and telemetry.
"""
import os

from education_applicant_verifier.events import EventBus, LoopEvent
from education_applicant_verifier.harness import Harness
from education_applicant_verifier.material import load_applications
from education_applicant_verifier.observability import Tracer
from education_applicant_verifier.profiles import teacher_profile
from education_applicant_verifier.store import RunStore
from education_applicant_verifier.verifier import FakeCredentialVerifier
from education_applicant_verifier.worker import FakeWorker

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "applications.json")


def build():
    apps = load_applications(DATA)
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    tracer = Tracer(bus)
    verifier = FakeCredentialVerifier()
    worker = FakeWorker()
    harness = Harness(teacher_profile(verifier), worker, tracer=tracer)
    return apps, harness, verifier, worker, tracer, events


def test_ranking_and_acceptance():
    apps, harness, *_ = build()
    result = harness.run(apps)
    ids = [e.applicant_id for e in result.ranking]
    # only the two valid-cert educators are scored; Maria (8) ranks above James (6)
    assert ids == ["maria", "james"]
    assert all(e.accepted for e in result.ranking)


def test_correction_loop_changes_behavior():
    apps, harness, *_ = build()
    result = harness.run(apps)
    by_id = {e.applicant_id: e for e in result.ranking}
    # James over-claimed experience on attempt 1, was corrected -> took 2 attempts
    assert by_id["james"].attempts == 2
    # Maria was grounded from the start -> 1 attempt
    assert by_id["maria"].attempts == 1
    assert any(a.type == "HALLUCINATED_QUALIFICATION" for a in result.alarms)


def test_ineligible_hard_gate():
    apps, harness, *_ = build()
    result = harness.run(apps)
    inelig = {e.applicant_id: e for e in result.ineligible}
    assert set(inelig) == {"robert", "sarah"}
    types = {a.type for e in result.ineligible for a in e.alarms}
    assert "CERT_EXPIRED" in types
    assert "CERT_NOT_FOUND" in types


def test_fraud_and_unavailable_escalate():
    apps, harness, *_ = build()
    result = harness.run(apps)
    esc = {e.applicant_id: e for e in result.escalations}
    assert set(esc) == {"evan", "nina"}
    # the fraud case fires a CRITICAL CERT_MISMATCH
    mismatch = [a for a in result.alarms if a.type == "CERT_MISMATCH"]
    assert mismatch and mismatch[0].severity.value == "critical"
    assert any(a.type == "TOOL_UNAVAILABLE" for a in result.alarms)


def test_replay_skips_rework():
    apps, harness, verifier, worker, _, _ = build()
    harness.store = RunStore()
    harness.run(apps)
    calls_after_first = verifier.calls
    worker_calls_after_first = worker.calls
    # second run: everything cached -> no new verifications or worker proposals
    result2 = harness.run(apps)
    assert verifier.calls == calls_after_first
    assert worker.calls == worker_calls_after_first
    # results still reconstructed from the store
    assert [e.applicant_id for e in result2.ranking] == ["maria", "james"]


def test_telemetry_recorded():
    apps, harness, _, _, tracer, events = build()
    harness.run(apps)
    # worker.propose spans == total attempts (Maria 1 + James 2)
    assert len(tracer.spans_named("worker.propose")) == 3
    # alarms were bridged onto the event bus
    alarm_events = [e for e in events if e.kind == "alarm"]
    assert any(e.data.get("type") == "CERT_MISMATCH" for e in alarm_events)
    # a decision event exists for every applicant that wasn't escalated
    assert sum(1 for e in events if e.kind == "decision") == 4
