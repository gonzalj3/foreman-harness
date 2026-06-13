"""API-level tests — call the endpoint functions directly (no extra HTTP deps)."""
import json

from education_applicant_verifier.server import ReviewRequest, review, samples


def test_samples_endpoint():
    s = samples()
    assert s["samples"]
    assert "fake-worker-v1" in s["workers"]


def _body(resp):
    return json.loads(resp.body)


def test_review_valid_accepts():
    applicant = {"id": "maria", "name": "Maria Alvarez", "role": "teacher", "cert_id": "TX-100",
                 "claimed_experience_years": 4, "document_experience_years": 4, "narrative": "x"}
    body = _body(review(ReviewRequest(applicant=applicant)))
    assert body["outcome"]["decision"] == "accepted"
    assert any(e["kind"] == "decision" for e in body["events"])


def test_review_fraud_escalates():
    applicant = {"id": "evan", "name": "Evan Fraud", "role": "substitute", "cert_id": "TX-100",
                 "claimed_experience_years": 2, "document_experience_years": 2, "narrative": ""}
    body = _body(review(ReviewRequest(applicant=applicant)))
    assert body["outcome"]["decision"] == "escalated"
    assert any(e["kind"] == "alarm" and e["data"]["type"] == "CERT_MISMATCH" for e in body["events"])


def test_review_hallucination_takes_two_attempts():
    applicant = {"id": "james", "name": "James Chen", "role": "teacher", "cert_id": "TX-200",
                 "claimed_experience_years": 8, "document_experience_years": 3, "narrative": "x"}
    body = _body(review(ReviewRequest(applicant=applicant)))
    assert body["outcome"]["record"]["attempts"] == 2
    assert any(e["kind"] == "alarm" and e["data"]["type"] == "HALLUCINATED_QUALIFICATION"
               for e in body["events"])
