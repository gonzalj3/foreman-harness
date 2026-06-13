"""CLI entrypoint: run the harness over a folder/file of applications.

Requires a model API key — an LLM worker is mandatory (no fake worker exists).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .harness import Harness
from .material import load_applications, render
from .profiles import teacher_profile
from .verifier import FakeCredentialVerifier
from .worker import DeepSeekWorker, GroqWorker, LLMWorker


def _build_worker():
    """Pick a worker from whichever model API key is set; None if no key."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMWorker()
    if os.environ.get("DEEPSEEK_API_KEY"):
        return DeepSeekWorker()
    if os.environ.get("GROQ_API_KEY"):
        return GroqWorker()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EducationApplicantVerifier — run the harness")
    parser.add_argument("path", help="path to applications .json (or a dir containing applications.json)")
    parser.add_argument("--json", action="store_true", help="print full JSON result")
    args = parser.parse_args(argv)

    worker = _build_worker()
    if worker is None:
        print("No model API key set. Set ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, or "
              "GROQ_API_KEY — an LLM worker is required.", file=sys.stderr)
        return 1

    path = args.path
    if os.path.isdir(path):
        path = os.path.join(path, "applications.json")

    apps = load_applications(path)
    harness = Harness(teacher_profile(FakeCredentialVerifier()), worker)
    result = harness.run(apps)
    rendered = render(result)

    if args.json:
        print(json.dumps(rendered, indent=2))
        return 0

    print(f"\n=== Ranked shortlist ({len(result.ranking)}) ===")
    for e in result.ranking:
        tag = "ACCEPT" if e.accepted else "reject"
        print(f"  {e.overall_score:>2}  [{tag}]  {e.name}  (attempts={e.attempts})")
    print(f"\n=== Ineligible ({len(result.ineligible)}) ===")
    for e in result.ineligible:
        a = e.alarms[0].type if e.alarms else "?"
        print(f"  {e.name}  -> {a}")
    print(f"\n=== Escalated ({len(result.escalations)}) ===")
    for e in result.escalations:
        print(f"  {e.name}  -> {e.reason}")
    print(f"\n=== Alarms ({len(result.alarms)}) ===")
    for a in result.alarms:
        print(f"  [{a.severity.value:>8}] {a.type}  ({a.applicant_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
