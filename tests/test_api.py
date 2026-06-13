"""API-level tests — call the endpoint functions directly (no extra HTTP deps).
The model is mocked; the worker is a real worker class.
"""
import json

from education_applicant_verifier.server import ReviewRequest, review, samples
from support import clean_eval, patch_openai_model


def _body(resp):
    return json.loads(resp.body)


def test_review_with_model_accepts(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    patch_openai_model(monkeypatch, clean_eval)
    applicant = {"id": "maria", "name": "Maria Alvarez", "role": "teacher", "cert_id": "TX-100",
                 "claimed_experience_years": 4, "document_experience_years": 4, "narrative": "x"}
    body = _body(review(ReviewRequest(applicant=applicant, worker="deepseek-v4-flash", verifier="fake")))
    assert body["outcome"]["decision"] == "accepted"
    assert any(e["kind"] == "decision" for e in body["events"])


def test_review_without_model_errors(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    body = _body(review(ReviewRequest(applicant={"id": "x", "name": "X"}, worker="none")))
    assert body["outcome"]["decision"] == "error"
    assert "API key" in body["outcome"]["record"]["reason"]


def test_samples_lists_no_workers_without_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = samples()
    assert s["workers"] == []  # no fakes, no keys -> an LLM is required
