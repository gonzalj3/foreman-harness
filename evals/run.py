"""Eval runner: score the harness's decisions against the gold set.

Runs each (candidate × job) case through the real harness with:
  - the live TEA verifier in FIXTURE mode (offline, deterministic; fixtures in
    evals/fixtures/tea), so the credential facts are real but reproducible, and
  - a real LLM worker (Claude / DeepSeek / Groq, whichever key is set).

Usage:
  ANTHROPIC_API_KEY=... python evals/run.py
  DEEPSEEK_API_KEY=...  python evals/run.py
The model judgment is non-deterministic, so this is a true eval — it reports a
score, not a pass/fail gate.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from education_applicant_verifier.harness import Harness
from education_applicant_verifier.material import from_dict
from education_applicant_verifier.profiles import teacher_profile
from education_applicant_verifier.verifier import TEACredentialVerifier
from education_applicant_verifier.worker import DeepSeekWorker, GroqWorker, LLMWorker

FIX = os.path.join(ROOT, "evals", "fixtures", "tea")
JOBS = os.path.join(ROOT, "evals", "jobs")
APPS = os.path.join(ROOT, "data", "applicants")


def build_worker():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMWorker()
    if os.environ.get("DEEPSEEK_API_KEY"):
        return DeepSeekWorker()
    if os.environ.get("GROQ_API_KEY"):
        return GroqWorker()
    return None


def decision_for(result, app_id: str) -> str:
    for e in result.escalations:
        if e.applicant_id == app_id:
            return "escalated"
    for e in result.ineligible:
        if e.applicant_id == app_id:
            return "ineligible"
    for e in result.ranking:
        if e.applicant_id == app_id:
            return "accepted" if e.accepted else "rejected"
    return "unknown"


def main() -> int:
    worker = build_worker()
    if worker is None:
        print("Set ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY to run evals.", file=sys.stderr)
        return 1

    gold = json.load(open(os.path.join(ROOT, "evals", "gold.json")))
    cases = gold["cases"]
    print(f"Running {len(cases)} eval cases with worker '{worker.name}'\n")

    passed = 0
    for c in cases:
        app = from_dict(json.load(open(os.path.join(APPS, c["candidate"] + ".json"))))
        job = json.load(open(os.path.join(JOBS, c["job"] + ".json")))
        app.metadata = {"job": job}
        verifier = TEACredentialVerifier(mode="fixture", fixture_dir=FIX)
        result = Harness(teacher_profile(verifier), worker).run([app])
        got = decision_for(result, app.id)
        ok = got == c["expected"]
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {c['candidate']:18} × {c['job']:22} expected={c['expected']:10} got={got}")
        if not ok:
            print(f"        expected because: {c['why']}")

    pct = round(100 * passed / len(cases))
    print(f"\nScore: {passed}/{len(cases)} ({pct}%) with {worker.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
