"""Observability layer (swappable backend).

For the first deploy this is a lightweight in-house tracer: it records spans in
memory (so tests can assert them) and bridges every alarm onto the event bus.
The OTel/OpenLLMetry -> Phoenix exporter is a drop-in replacement here later
(the rest of the harness does not change).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

from .events import EventBus, LoopEvent
from .types import Alarm


class Span:
    def __init__(self, name: str, attrs: dict) -> None:
        self.name = name
        self.attrs = attrs
        self.events: list[dict] = []


class Tracer:
    def __init__(self, bus: Optional[EventBus] = None) -> None:
        self.bus = bus or EventBus()
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **attrs):
        sp = Span(name, dict(attrs))
        self.spans.append(sp)
        try:
            yield sp
        finally:
            pass

    def event(self, event: LoopEvent) -> None:
        self.bus.emit(event)

    def record_alarm(self, alarm: Alarm, span: Optional[Span] = None) -> None:
        """Bridge: an alarm becomes a span event AND a LoopEvent on the bus."""
        if span is not None:
            span.events.append({"alarm": alarm.type, "severity": alarm.severity.value})
        self.bus.emit(LoopEvent(
            kind="alarm",
            applicant_id=alarm.applicant_id,
            data={
                "type": alarm.type,
                "severity": alarm.severity.value,
                "recommended_action": alarm.recommended_action,
                "context": alarm.context,
            },
        ))

    def spans_named(self, name: str) -> list[Span]:
        return [s for s in self.spans if s.name == name]
