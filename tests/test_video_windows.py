"""Which part of a kept video plays: the part where something happens (#1949)."""

import pytest

from immich_memories.analysis.editorial_video_windows import choose_window


def _probes(duration, busy):
    """Activity every half second; `busy` holds the seconds where something moves."""
    times = [i * 0.5 for i in range(int(duration / 0.5))]
    return [(t, 3.0 if busy[0] <= t <= busy[1] else 0.1) for t in times]


def test_the_window_moves_to_where_the_riders_cross():
    start = choose_window(_probes(12.24, (7.5, 9.5)), duration=12.24, hold=4.0)

    assert 6.0 <= start <= 7.5, "the first 3.5 s that always play must hold the action"


def test_a_clip_busy_everywhere_keeps_its_opening():
    assert choose_window(_probes(20.0, (0.0, 20.0)), duration=20.0, hold=6.0) == 0.0


def test_a_clip_no_longer_than_its_hold_plays_whole():
    assert choose_window(_probes(5.0, (3.0, 4.5)), duration=5.0, hold=5.0) == 0.0


def test_speech_pulls_the_window_onto_the_conversation():
    probes = _probes(20.0, (0.0, 20.0))
    start = choose_window(probes, duration=20.0, hold=6.0, speech=[(11.0, 16.0)])

    assert start <= 11.0 and start + 6.0 >= 16.0


def test_no_probes_keeps_the_opening():
    assert choose_window([], duration=30.0, hold=6.0) == pytest.approx(0.0)


def test_the_real_planner_starts_each_kept_video_on_its_action(tmp_path):
    from dataclasses import replace

    from immich_memories.analysis.editorial_structure_planner import plan_structure
    from immich_memories.analysis.editorial_video_windows import place_windows
    from immich_memories.api.models import AssetType
    from immich_memories.processing.editorial_timing import build_editorial_timing_policy
    from tests.test_editorial_duration_planner_integration import source
    from tests.test_editorial_timing import _ports

    captured = source(tmp_path, seconds=60, pictures=50)
    captured = replace(
        captured,
        assets={
            key: asset.model_copy(update={"type": AssetType.VIDEO, "duration_seconds": 12.0})
            for key, asset in captured.assets.items()
        },
    )
    timing = build_editorial_timing_policy(
        config=captured.config,
        target_seconds=60,
        memory_type=captured.case.product,
        transition="cut",
    )
    riders = _probes(12.0, (7.5, 9.5))

    plan = plan_structure(
        replace(captured, render_timing=timing),
        replace(_ports(), resolve_windows=lambda cs: place_windows(cs, lambda _id: riders)),
    ).plan

    videos = [c for c in plan["carriers"] if c["kind"] == "video"]
    assert videos
    for carrier in videos:
        assert carrier["start_time"] <= 7.5 <= 9.5 <= carrier["end_time"], "the riders cross"
        assert carrier["end_time"] - carrier["start_time"] == carrier["seconds"]
        assert carrier["end_time"] <= 12.0
