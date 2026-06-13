"""Vercel Python serverless entrypoint.

Exposes the FastAPI app so Vercel can serve the harness API (and dashboard HTML).
The vercel.json rewrite routes all paths to this function; FastAPI handles its own
internal routing (/health, /api/samples, /api/review).
"""
import os
import sys

# make the repo root importable so `education_applicant_verifier` resolves
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from education_applicant_verifier.server import app  # noqa: E402,F401
