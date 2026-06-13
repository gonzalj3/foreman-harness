"""Persistence + replay.

Each applicant's completed result is a checkpoint. On a re-run, completed
applicants are served from the store instead of re-running the worker/verifier —
that is the "replay skips prior stages" behavior. The JSON flush is best-effort
for durability/inspection; in-session replay uses the in-memory cache.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .types import Application


class RunStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        # applicant_id -> (kind, result_object)   kind in {"scored","ineligible","escalated"}
        self._cache: dict[str, tuple[str, object]] = {}

    def key(self, application: Application) -> str:
        return application.id

    def get(self, application: Application):
        return self._cache.get(self.key(application))

    def put(self, application: Application, kind: str, result_object) -> None:
        self._cache[self.key(application)] = (kind, result_object)
        self._flush()

    def _flush(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            data = {k: {"kind": v[0]} for k, v in self._cache.items()}
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception:
            pass
