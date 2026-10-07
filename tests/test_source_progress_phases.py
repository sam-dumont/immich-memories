"""A long selection stage keeps the scheduled-run phase log moving (#2199)."""

from __future__ import annotations

from immich_memories.cli.source_progress import SourceProgressReporter
from tests.test_surface_parity import CountingDisplay


def _counted(done: int, total: int = 659, label: str = "Preparing pictures") -> dict:
    return {
        "phase_label": label,
        "stage_identity": (label, total),
        "current_index": done,
        "total_items": total,
    }


def _reporter(events: list, now: list[float]) -> SourceProgressReporter:
    return SourceProgressReporter(
        CountingDisplay(),
        0,
        on_phase=lambda current, total, message: events.append((current, total, message)),
        clock=lambda: now[0],
    )


def test_a_new_stage_is_reported_at_once():
    events: list = []
    reporter = _reporter(events, [0.0])

    reporter(_counted(0))

    assert events == [(0, 659, "Preparing pictures")]


def test_a_quiet_stretch_is_reported_every_minute_even_with_few_pictures_done():
    events: list = []
    now = [0.0]
    reporter = _reporter(events, now)
    reporter(_counted(0))

    now[0] = 30.0
    reporter(_counted(3))
    assert len(events) == 1

    now[0] = 61.0
    reporter(_counted(4))
    assert events[-1] == (4, 659, "Preparing pictures")


def test_every_twenty_fifth_picture_is_reported_however_fast_they_come():
    events: list = []
    reporter = _reporter(events, [0.0])
    reporter(_counted(0))

    for done in range(1, 60):
        reporter(_counted(done))

    assert [e[0] for e in events] == [0, 25, 50]


def _unbounded(label: str) -> dict:
    return {"phase_label": label, "indeterminate": True}


def test_each_new_uncounted_stage_is_reported_not_only_the_first():
    """The family-viewing check and the picture review are uncounted stages in a row (#2219)."""
    events: list = []
    reporter = _reporter(events, [0.0])

    reporter(_unbounded("Editing the memory: 149 pictures going into the family-viewing check"))
    reporter(_unbounded("Editing the memory: 149 pictures going into the family-viewing check"))
    reporter(_unbounded("Editing the memory: 149 pictures going into the picture review"))

    assert [e[2] for e in events] == [
        "Editing the memory: 149 pictures going into the family-viewing check",
        "Editing the memory: 149 pictures going into the picture review",
    ]
