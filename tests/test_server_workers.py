"""Regression test: each worker factory must build its OWN model (no late-binding
closure bug where every factory ends up using the last model)."""
from education_applicant_verifier import server


def test_each_factory_builds_its_own_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "y")
    workers = server.available_workers()
    assert "claude-haiku-4-5" in workers and "deepseek-v4-flash" in workers
    # the Anthropic factory must NOT build a deepseek model (the bug we fixed)
    assert workers["claude-haiku-4-5"]().model == "claude-haiku-4-5"
    assert workers["deepseek-v4-flash"]().model == "deepseek-v4-flash"


def test_no_keys_only_fakes(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert set(server.available_workers()) == {"fake-worker-v1", "strict-fake-worker-v1"}
