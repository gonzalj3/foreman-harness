"""Workers (the AI). Swappable behind the Worker protocol.

FakeWorker is deterministic and offline so the whole harness can be tested at
zero cost. Crucially it *changes its behavior on feedback*: on the first attempt
it asserts the applicant's claimed experience (which may exceed what the document
supports); once a guardrail/checkpoint returns an UNGROUNDED_CLAIM failure, it
re-proposes using only the document-supported value. This exercises the
correction loop the challenge grades.
"""
from __future__ import annotations

import json
import os
import urllib.request

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


# ---------------------------------------------------------------------------
# Real LLM workers — both produce the same Proposal shape the harness gates.
# The model returns JSON; the harness's checkpoints validate it (and re-prompt
# via prior_failures if it's wrong), so the worker stays a thin proposer.
# ---------------------------------------------------------------------------

def _system_prompt() -> str:
    return (
        "You are an impartial evaluator for education-sector job applications. "
        "Score the applicant against each rubric criterion on a 0-10 scale. "
        "Base every score ONLY on facts stated in the application, and for each "
        "criterion cite the specific text you relied on in 'evidence'. Credit "
        "'experience_years' only up to what the application supports. Never use "
        "age, gender, race, or other protected-class reasoning. "
        "Respond with a single JSON object and nothing else."
    )


def _build_user_prompt(application: Application, rubric: list[str], prior_failures: list[Failure]) -> str:
    app = {
        "name": application.name,
        "role": application.role,
        "narrative": application.narrative,
        "supported_experience_years": application.document_experience_years,
    }
    parts = [
        "Application:",
        json.dumps(app, indent=2),
        "",
        f"Score exactly these rubric criteria, using these names: {rubric}.",
        "Return a JSON object with keys: overall_score (int 0-10), "
        "recommendation ('advance' or 'reject'), rationale (string), "
        "experience_years (int), and criteria (array of {name, score 0-10, evidence}).",
    ]
    if prior_failures:
        joined = "; ".join(f"{f.code}: {f.message}" for f in prior_failures)
        parts += ["", f"Your previous attempt was REJECTED for: {joined}. Fix these issues now."]
    return "\n".join(parts)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def _proposal_from_json(data: dict, applicant_id: str) -> Proposal:
    criteria = [
        CriterionScore(
            name=str(c.get("name", "?")),
            score=int(c.get("score", 0)),
            evidence=str(c.get("evidence", "")).strip(),
        )
        for c in data.get("criteria", [])
    ]
    return Proposal(
        applicant_id=applicant_id,
        overall_score=int(data.get("overall_score", 0)),
        criteria=criteria,
        recommendation=str(data.get("recommendation", "reject")),
        claims={"experience_years": int(data.get("experience_years", 0))},
        rationale=str(data.get("rationale", "")),
    )


class LLMWorker:
    """Claude worker (Anthropic SDK). Default model: Opus 4.8 (configurable)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
        self.name = self.model
        self.calls = 0
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            import anthropic  # lazy so the module imports without the SDK installed

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        return self._client

    def propose(self, application: Application, rubric: list[str], prior_failures: list[Failure]) -> Proposal:
        self.calls += 1
        client = self._client_lazy()
        resp = client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=_system_prompt(),
            messages=[{"role": "user", "content": _build_user_prompt(application, rubric, prior_failures)}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "{}")
        return _proposal_from_json(json.loads(_extract_json(text)), application.id)


class _OpenAICompatibleWorker:
    """Base for any provider that speaks the OpenAI chat-completions shape
    (Groq, DeepSeek, OpenAI, Together, OpenRouter, ...). Stdlib only — adding a
    new provider is just three constants. Same Worker interface as everything
    else, so the harness is unchanged and providers can be swapped live.
    """

    URL = ""           # chat-completions endpoint
    KEY_ENV = ""       # env var holding the API key
    MODEL_ENV = ""     # env var to override the model
    DEFAULT_MODEL = "" # model id used when MODEL_ENV is unset

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get(self.MODEL_ENV, self.DEFAULT_MODEL)
        self.name = self.model
        self.calls = 0

    def propose(self, application: Application, rubric: list[str], prior_failures: list[Failure]) -> Proposal:
        self.calls += 1
        key = os.environ.get(self.KEY_ENV)
        if not key:
            raise RuntimeError(f"{self.KEY_ENV} not set")
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _system_prompt() + " Output ONLY the JSON object."},
                {"role": "user", "content": _build_user_prompt(application, rubric, prior_failures)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            self.URL,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode())
        content = payload["choices"][0]["message"]["content"]
        return _proposal_from_json(json.loads(_extract_json(content)), application.id)


class GroqWorker(_OpenAICompatibleWorker):
    """Open-source model via Groq (default: Gemma `gemma2-9b-it`)."""

    URL = "https://api.groq.com/openai/v1/chat/completions"
    KEY_ENV = "GROQ_API_KEY"
    MODEL_ENV = "GROQ_MODEL"
    DEFAULT_MODEL = "gemma2-9b-it"


class DeepSeekWorker(_OpenAICompatibleWorker):
    """DeepSeek via its OpenAI-compatible API (default: `deepseek-chat` = V3;
    set DEEPSEEK_MODEL=deepseek-reasoner for R1)."""

    URL = "https://api.deepseek.com/chat/completions"
    KEY_ENV = "DEEPSEEK_API_KEY"
    MODEL_ENV = "DEEPSEEK_MODEL"
    DEFAULT_MODEL = "deepseek-chat"
