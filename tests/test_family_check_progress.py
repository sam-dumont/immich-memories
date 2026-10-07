"""The family-viewing check counts its pictures out loud while it works (#2219)."""

from __future__ import annotations

from immich_memories.analysis.editorial_structure_finishing import counted_verdicts
from immich_memories.operations.cut_progress import StageUpdate, announcing_stages


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_each_picture_checked_moves_a_counted_stage_at_most_every_few_seconds() -> None:
    heard: list[StageUpdate] = []
    clock = _Clock()
    verdicts = counted_verdicts(lambda _row: "share", total=149, clock=clock, every_seconds=5.0)

    with announcing_stages(heard.append):
        for number in range(149):
            clock.now += 1.0
            assert verdicts({"asset_id": str(number)}) == "share"

    assert 20 <= len(heard) <= 40
    assert all(update.counted and update.total == 149 for update in heard)
    assert [u.done for u in heard] == sorted(u.done for u in heard)
    assert heard[-1].done == 149
    assert "family-viewing check" in heard[0].label


def test_checks_past_the_total_never_overflow_the_count() -> None:
    heard: list[StageUpdate] = []
    verdicts = counted_verdicts(lambda _row: None, total=2, clock=_Clock(), every_seconds=0.0)

    with announcing_stages(heard.append):
        for number in range(5):
            verdicts({"asset_id": str(number)})

    assert max(u.done or 0 for u in heard) == 2
