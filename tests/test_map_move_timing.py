"""A map move: an eased flight, then a still hold on the destination with its name."""

from __future__ import annotations

import pytest

from immich_memories.processing.map_move_timing import MapMoveTiming


def test_a_short_hop_takes_the_shortest_move_and_a_long_flight_the_longest() -> None:
    timing = MapMoveTiming(min_seconds=6.0, max_seconds=8.0)

    assert timing.seconds_for(31.0) == pytest.approx(6.0, abs=0.05)
    assert timing.seconds_for(9000.0) == 8.0
    assert 6.0 < timing.seconds_for(400.0) < 8.0
    assert timing.seconds_for(400.0) < timing.seconds_for(1200.0)


def test_the_move_eases_in_and_out_and_ends_on_two_still_seconds() -> None:
    timing = MapMoveTiming()

    frames = timing.schedule(6.0, fps=30.0)

    assert len(frames) == 180
    assert frames[0] == 0.0
    assert frames[-60:] == [1.0] * 60
    assert frames == sorted(frames)
    first_step, middle_step = frames[1] - frames[0], frames[60] - frames[59]
    assert first_step < middle_step / 4


def test_the_name_is_fully_up_for_the_whole_hold() -> None:
    timing = MapMoveTiming()

    alphas = timing.label_alphas(6.0, fps=30.0)

    assert len(alphas) == 180
    assert alphas[0] == 0.0
    assert alphas[-60:] == [1.0] * 60
