"""The harness loop — ties the four pillars + the tool around the worker.

For each applicant:
  1. verify credential (tool, harness-owned)
  2. credential hard-gate -> eligible / ineligible / escalate
  3. if eligible, worker proposes -> guardrails + checkpoint gate
  4. on fail, return the specific failure and let the worker revise (bounded)
  5. pass -> persist; retries exhausted -> escalate
  6. rank deterministically (the harness sorts, not the LLM)

Every step emits a LoopEvent (dashboard) and is wrapped in a span (observability).
The worker is never asked to do I/O or enforce rules.
"""
from __future__ import annotations

from . import checkpoints, guardrails
from .alarms import AlarmType, raise_alarm
from .events import LoopEvent
from .observability import Tracer
from .profiles import RoleProfile
from .types import Application, Escalation, Evaluation, Failure, RunResult, Worker


class Harness:
    def __init__(self, profile: RoleProfile, worker: Worker, tracer: Tracer | None = None, store=None) -> None:
        self.profile = profile
        self.worker = worker
        self.verifier = profile.verifier
        self.tracer = tracer or Tracer()
        self.store = store

    def run(self, applications: list[Application]) -> RunResult:
        result = RunResult()
        self.tracer.event(LoopEvent("run_started", data={"count": len(applications),
                                                         "profile": self.profile.name,
                                                         "worker": self.worker.name}))
        for app in applications:
            cached = self.store.get(app) if self.store else None
            if cached:
                self._dispatch(result, *cached)
                self.tracer.event(LoopEvent("replayed", app.id))
                continue
            self._process(result, app)

        result.ranking.sort(key=lambda e: e.overall_score, reverse=True)
        self.tracer.event(LoopEvent("run_completed", data={
            "ranked": len(result.ranking),
            "ineligible": len(result.ineligible),
            "escalations": len(result.escalations),
        }))
        return result

    # --- internals ---

    def _dispatch(self, result: RunResult, kind: str, obj) -> None:
        if kind == "scored":
            result.ranking.append(obj)
        elif kind == "ineligible":
            result.ineligible.append(obj)
        elif kind == "escalated":
            result.escalations.append(obj)
        result.alarms.extend(getattr(obj, "alarms", []))

    def _process(self, result: RunResult, app: Application) -> None:
        t = self.tracer
        t.event(LoopEvent("applicant_started", app.id, data={"name": app.name, "role": app.role}))

        with t.span("applicant", applicant_id=app.id) as sp:
            # 1. credential verification (the tool)
            with t.span("verify_credential", applicant_id=app.id):
                cred = self.verifier.verify(app.cert_id, app.name)
            t.event(LoopEvent("credential", app.id, data={
                "status": cred.status.value, "holder": cred.holder_name, "cert_id": cred.cert_id}))

            # 2. hard-gate
            decision, cred_alarms, reason = checkpoints.credential_gate(app, cred)
            for a in cred_alarms:
                t.record_alarm(a, sp)

            if decision == "escalate":
                esc = Escalation(app.id, app.name, reason, alarms=list(cred_alarms))
                t.event(LoopEvent("escalated", app.id, data={"reason": reason}))
                result.escalations.append(esc)
                result.alarms.extend(cred_alarms)
                if self.store:
                    self.store.put(app, "escalated", esc)
                return

            if decision == "ineligible":
                ev = Evaluation(app.id, app.name, "ineligible", eligible=False, accepted=False,
                                overall_score=0, attempts=0, proposal=None, credential=cred,
                                alarms=list(cred_alarms))
                t.event(LoopEvent("decision", app.id, data={"status": "ineligible", "reason": reason}))
                result.ineligible.append(ev)
                result.alarms.extend(cred_alarms)
                if self.store:
                    self.store.put(app, "ineligible", ev)
                return

            # 3-5. eligible -> worker proposes, gated, with bounded correction loop
            failures: list = []
            loop_alarms: list = []
            proposal = None
            attempt = 0
            passed = False

            while attempt < self.profile.max_attempts:
                attempt += 1
                t.event(LoopEvent("attempt_started", app.id, attempt=attempt))
                with t.span("worker.propose", applicant_id=app.id, attempt=attempt):
                    try:
                        proposal = self.worker.propose(app, self.profile.rubric, failures)
                    except Exception as e:  # a model can error or return unparseable output
                        failures = [Failure("WORKER_ERROR", f"{type(e).__name__}: {e}"[:200])]
                        t.event(LoopEvent("worker_error", app.id, attempt=attempt,
                                          data={"error": str(e)[:200]}))
                        continue
                t.event(LoopEvent("worker_proposed", app.id, attempt=attempt, data={
                    "overall": proposal.overall_score, "recommendation": proposal.recommendation}))

                g = guardrails.check(proposal, app, self.profile.guardrail_config)
                c = checkpoints.check_evaluation(proposal, app)
                for a in (g.alarms + c.alarms):
                    t.record_alarm(a, sp)
                loop_alarms.extend(g.alarms + c.alarms)

                t.event(LoopEvent("guardrail", app.id, attempt=attempt, data={
                    "passed": g.passed, "failures": [f.code for f in g.failures]}))
                t.event(LoopEvent("checkpoint", app.id, attempt=attempt, data={
                    "passed": c.passed, "failures": [f.code for f in c.failures]}))

                if g.passed and c.passed:
                    passed = True
                    break
                failures = g.failures + c.failures

            if not passed:
                a = raise_alarm(AlarmType.RETRY_BUDGET_EXCEEDED, app.id, {"attempts": attempt})
                t.record_alarm(a, sp)
                loop_alarms.append(a)
                esc = Escalation(app.id, app.name,
                                 "worker could not produce a valid evaluation within the retry budget",
                                 failures=list(failures), alarms=list(loop_alarms))
                t.event(LoopEvent("escalated", app.id, data={"reason": esc.reason}))
                result.escalations.append(esc)
                result.alarms.extend(loop_alarms)
                if self.store:
                    self.store.put(app, "escalated", esc)
                return

            accepted = proposal.recommendation == "advance" and proposal.overall_score >= self.profile.pass_score
            ev = Evaluation(app.id, app.name, "scored", eligible=True, accepted=accepted,
                            overall_score=proposal.overall_score, attempts=attempt,
                            proposal=proposal, credential=cred, alarms=list(loop_alarms))
            t.event(LoopEvent("decision", app.id, data={
                "status": "accepted" if accepted else "rejected",
                "score": proposal.overall_score, "attempts": attempt}))
            result.ranking.append(ev)
            result.alarms.extend(loop_alarms)
            if self.store:
                self.store.put(app, "scored", ev)
