"""Workers (the AI). Each worker is a thin proposer behind the Worker protocol:
it returns a Proposal; the harness verifies, gates, and re-prompts it. An LLM is
required — there is no offline/fake worker (tests mock the model's network call
against the real worker classes).
"""
from __future__ import annotations

import json
import os
import urllib.request

from .types import Application, CriterionScore, Failure, Proposal


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
        "'experience_years' only up to what the application supports. "
        "A candidate may only be recommended ('advance') if their verified TEA "
        "certification covers the job's subject area and grade level. Never use "
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
    parts: list[str] = []

    job = (getattr(application, "metadata", None) or {}).get("job")
    if job:
        jd = {
            k: job[k]
            for k in ("title", "employer", "summary", "required_education",
                      "required_credentials", "preferred_experience", "skills", "rubric_hints")
            if job.get(k)
        }
        parts += [
            "Job description — judge the applicant's FIT against THIS specific role:",
            json.dumps(jd, indent=2),
            "",
        ]

    cred = (getattr(application, "metadata", None) or {}).get("credential")
    if cred:
        parts += [
            "Verified TEA certification for this applicant (from the live TEA lookup):",
            json.dumps({
                "status": cred.get("status"),
                "certified_subject_areas": cred.get("certifications"),
                "certified_grade_bands": cred.get("grade_bands"),
                "expires": cred.get("expires"),
            }, indent=2),
            "",
            "SUBJECT-MATCH REQUIREMENT: to recommend 'advance', the certified subject "
            "areas and grade bands above MUST cover this job's subject and grade level. "
            "If the applicant is not certified in the job's subject (e.g. a Science role "
            "but no Science certification), treat it as disqualifying: set 'fit' to 3 or "
            "lower, set recommendation to 'reject', and name the missing certification in "
            "the evidence and rationale.",
            "",
        ]

    parts += [
        "Application:",
        json.dumps(app, indent=2),
        "",
        f"Score exactly these rubric criteria, using these names: {rubric}.",
        "Score 'fit' specifically by how well the applicant matches the job's "
        "requirements and responsibilities above." if job else
        "Score 'fit' by how well the applicant suits an education-sector role.",
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
        # Cheapest Claude tier by default (user-selected); override with CLAUDE_MODEL.
        self.model = model or os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
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
    DEFAULT_MODEL = "deepseek-v4-flash"  # cheapest tier; deepseek-v4-pro via DEEPSEEK_MODEL
