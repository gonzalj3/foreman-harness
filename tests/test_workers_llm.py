"""Offline tests for the real-model workers: prompt construction + JSON parsing.

The live API calls (Claude, Groq/Gemma) are exercised manually with keys set;
these tests cover everything that doesn't touch the network so the suite stays
deterministic and free.
"""
from education_applicant_verifier.types import Application, Failure
from education_applicant_verifier.worker import (
    DeepSeekWorker,
    GroqWorker,
    LLMWorker,
    _build_user_prompt,
    _extract_json,
    _proposal_from_json,
    _system_prompt,
)


def _app():
    return Application(id="x", name="X", role="teacher", cert_id=None,
                       claimed_experience_years=5, document_experience_years=5,
                       narrative="5 years teaching 4th grade math")


def test_proposal_from_json_maps_fields():
    data = {
        "overall_score": 8, "recommendation": "advance", "rationale": "strong",
        "experience_years": 5,
        "criteria": [
            {"name": "experience", "score": 8, "evidence": "5 years teaching"},
            {"name": "fit", "score": 7, "evidence": "math focus"},
        ],
    }
    p = _proposal_from_json(data, "x")
    assert p.overall_score == 8
    assert p.recommendation == "advance"
    assert p.claims["experience_years"] == 5
    assert len(p.criteria) == 2 and p.criteria[0].name == "experience"


def test_extract_json_tolerates_prose():
    raw = "Here is the evaluation:\n{\"overall_score\": 6, \"criteria\": []}\nThanks!"
    assert _extract_json(raw).startswith("{") and _extract_json(raw).endswith("}")


def test_user_prompt_includes_feedback_for_revision():
    prompt = _build_user_prompt(_app(), ["experience", "fit"],
                                [Failure("UNGROUNDED_CLAIM", "claimed 9 supported 5", "experience_years")])
    assert "UNGROUNDED_CLAIM" in prompt
    assert "experience" in prompt


def test_system_prompt_states_constraints():
    s = _system_prompt().lower()
    assert "protected-class" in s or "protected class" in s
    assert "json" in s


def test_worker_names_reflect_model():
    assert LLMWorker("claude-opus-4-8").name == "claude-opus-4-8"
    assert GroqWorker("gemma2-9b-it").name == "gemma2-9b-it"
    assert DeepSeekWorker("deepseek-chat").name == "deepseek-chat"


def test_openai_compatible_providers_configured():
    assert GroqWorker().KEY_ENV == "GROQ_API_KEY" and "groq.com" in GroqWorker().URL
    assert DeepSeekWorker().KEY_ENV == "DEEPSEEK_API_KEY" and "deepseek.com" in DeepSeekWorker().URL
