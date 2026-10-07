"""The render reports clips encoded n/N as phase events while it works (#2219)."""

from __future__ import annotations

from immich_memories.generate_progress import render_progress_events
from immich_memories.operations.phases import OperationalPhase


class _Operational:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def emit(self, phase, current, total, message):
        self.events.append((phase, current, total, message))


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def test_assembly_progress_becomes_render_events_at_most_every_interval() -> None:
    operational, clock, inner = _Operational(), _Clock(), []
    callback = render_progress_events(
        lambda pct, msg: inner.append((pct, msg)), operational, 149, clock=clock, every_seconds=30
    )

    callback(0.0, "Encoding video...")
    clock.now = 10
    callback(0.1, "Encoding video...")
    clock.now = 31
    callback(0.5, "Encoding video...")

    assert [e[1] for e in operational.events] == [0, 74]
    assert all(e[0] is OperationalPhase.RENDER and e[2] == 149 for e in operational.events)
    assert len(inner) == 3, "the progress bar still hears every report"


def test_a_render_with_no_progress_bar_still_reports_events() -> None:
    operational = _Operational()
    callback = render_progress_events(None, operational, 10, clock=_Clock(), every_seconds=30)

    callback(1.0, "Done")

    assert operational.events == [(OperationalPhase.RENDER, 10, 10, "Done")]
