import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
# repo root (so `education_applicant_verifier` resolves) + tests dir (so `support` resolves)
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))
