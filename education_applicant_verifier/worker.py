"""Workers (the AI). Swappable behind the Worker protocol.

FakeWorker is deterministic and offline so the whole harness can be tested at
zero cost. Crucially it *changes its behavior on feedback*: on the first attempt
it asserts the applicant's claimed experience (which may exceed what the document
supports); once a guardrail/checkpoint returns an UNGROUNDED_CLAIM failure, it
re-proposes using only the document-supported value. This exercises the
correction loop the challenge grades.
"""
from __future__ import annotations

from .types import Application, CriterionScore, Failure, Proposal


class FakeWorker:
    name = "fake-worker-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self, application: Application, rubric: list[str], prior_failures: list[Failure]
    ) -> Proposal:
        self.calls += 1

        experience_was_flagged = any(
            f.code == "UNGROUNDED_CLAIM" and f.field == "experience_years"
            for f in prior_failures
        )
        years = (
            application.document_experience_years
            if experience_was_flagged
            else application.claimed_experience_years
        )

        criteria = [
            CriterionScore(
                name="experience",
                score=min(10, years * 2),
                evidence=f"{years} years of relevant experience indicated in the application",
            ),
            CriterionScore(
                name="fit",
                score=7,
                evidence=(application.narrative or "role-relevant background")[:80],
            ),
        ]
        overall = round(sum(c.score for c in criteria) / len(criteria))
        return Proposal(
            applicant_id=application.id,
            overall_score=overall,
            criteria=criteria,
            recommendation="advance" if overall >= 6 else "reject",
            claims={"experience_years": years},
            rationale=f"Candidate demonstrates {years} years of experience and adequate role fit.",
        )


class StrictFakeWorker(FakeWorker):
    """A second, stricter worker — used to demonstrate live worker-swap (bonus).

    Same interface; scores fit lower, so rankings differ when swapped in.
    """
    name = "strict-fake-worker-v1"

    def propose(self, application, rubric, prior_failures):
        proposal = super().propose(application, rubric, prior_failures)
        for c in proposal.criteria:
            if c.name == "fit":
                c.score = 5
        proposal.overall_score = round(sum(c.score for c in proposal.criteria) / len(proposal.criteria))
        proposal.recommendation = "advance" if proposal.overall_score >= 6 else "reject"
        return proposal
