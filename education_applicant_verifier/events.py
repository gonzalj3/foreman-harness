"""LoopEvents + a tiny in-process event bus.

The harness emits a LoopEvent at every stage. The same stream feeds (a) the
dashboard via SSE and (b) observability. Keeping it a plain bus means tests can
subscribe and assert exactly what the harness did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class LoopEvent:
    kind: str                       # applicant_started, credential, attempt_started, worker_proposed,
                                    # guardrail, checkpoint, alarm, escalated, decision, ...
    applicant_id: Optional[str] = None
    attempt: Optional[int] = None
    data: dict = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[LoopEvent], None]] = []

    def subscribe(self, fn: Callable[[LoopEvent], None]) -> Callable[[LoopEvent], None]:
        self._subscribers.append(fn)
        return fn

    def emit(self, event: LoopEvent) -> None:
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:
                # the bus must never break the loop
                pass
