"""Test support: mock the model's network call so tests exercise the REAL worker
classes offline. There is no fake worker — we patch the HTTP boundary instead.
"""
import json
import re


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def patch_openai_model(monkeypatch, content_fn):
    """Patch the OpenAI-compatible workers' urlopen (DeepSeek/Groq) to return
    `content_fn(user_prompt)` as the model's message content."""
    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        user = body["messages"][-1]["content"]
        return _Resp({"choices": [{"message": {"content": content_fn(user)}}]})

    monkeypatch.setattr(
        "education_applicant_verifier.worker.urllib.request.urlopen", fake_urlopen
    )


def _supported_years(user: str) -> int:
    m = re.search(r'"supported_experience_years":\s*(\d+)', user)
    return int(m.group(1)) if m else 0


def clean_eval(user: str) -> str:
    """A well-formed, grounded evaluation (experience matches what the doc supports)."""
    yrs = _supported_years(user)
    return json.dumps({
        "overall_score": 8, "recommendation": "advance", "rationale": "strong fit",
        "experience_years": yrs,
        "criteria": [
            {"name": "experience", "score": 8, "evidence": "relevant experience cited in the application"},
            {"name": "fit", "score": 7, "evidence": "matches the role requirements"},
        ],
    })


def revise_eval(user: str) -> str:
    """First attempt omits a citation (checkpoint fails); the revision includes it."""
    yrs = _supported_years(user)
    evidence = "now citing specific evidence from the application" if "REJECTED" in user else ""
    return json.dumps({
        "overall_score": 8, "recommendation": "advance", "rationale": "ok",
        "experience_years": yrs,
        "criteria": [
            {"name": "experience", "score": 8, "evidence": evidence},
            {"name": "fit", "score": 7, "evidence": "fit cited"},
        ],
    })
