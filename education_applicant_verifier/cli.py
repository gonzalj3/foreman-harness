"""CLI entrypoint: run the harness over a folder/file of applications with fakes."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .harness import Harness
from .material import load_applications, render
from .profiles import teacher_profile
from .verifier import FakeCredentialVerifier
from .worker import FakeWorker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EducationApplicantVerifier — run the harness")
    parser.add_argument("path", help="path to applications .json (or a dir containing applications.json)")
    parser.add_argument("--json", action="store_true", help="print full JSON result")
    args = parser.parse_args(argv)

    path = args.path
    if os.path.isdir(path):
        path = os.path.join(path, "applications.json")

    apps = load_applications(path)
    harness = Harness(teacher_profile(FakeCredentialVerifier()), FakeWorker())
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
