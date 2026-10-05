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


def test_an_announcer_does_not_pull_the_window_off_the_riders():
    """Measured on a finish-line clip: the detector hears the crowd PA in the first nine
    seconds, the picture changes only when the riders cross (#1949)."""
    pa = [(0.0, 2.3), (2.7, 4.3), (7.1, 9.1), (13.9, 15.2)]
    start = choose_window(_probes(20.3, (15.0, 17.0)), duration=20.3, hold=6.0, speech=pa)

    assert start <= 15.0 and start + 6.0 >= 17.0


def test_a_flat_picture_follows_the_speech():
    """The trip joke: the walk changes the picture evenly; what matters is who talks."""
    joke = [(0.9, 2.0), (2.4, 3.6), (4.0, 6.7)]
    start = choose_window(_probes(6.76, (0.0, 6.76)), duration=6.76, hold=6.0, speech=joke)

    assert 0.5 <= start <= 0.9, "the window starts on the first line, not the silent step"


# One loudness reading per second of a birthday clip (dB), as measured: singing throughout,
# the candles blown out and cheered at 27 s, more cheering later on.
CAKE_DB = [-34, -31, -29, -30, -29, -31, -31, -27, -29, -30, -34, -33, -29, -28, -31, -27,
           -32, -32, -30, -29, -30, -35, -37, -32, -23, -41, -28, -17, -21, -24, -32, -25,
           -28, -35, -36, -38, -31, -26, -24, -22, -19, -24, -26, -25, -24, -24, -36, -36,
           -37, -28, -25, -22, -26, -26, -27, -30, -28, -21, -29, -29, -19, -26]  # fmt: skip
CAKE_SPEECH = [(0.0, 0.7), (1.4, 3.7), (6.3, 8.2), (8.9, 11.2), (11.5, 15.1), (17.0, 17.2),
               (20.3, 23.1), (23.6, 25.3), (25.8, 27.6), (28.7, 34.4), (34.6, 35.7),
               (36.2, 43.1), (49.1, 50.8), (56.0, 62.5)]  # fmt: skip


def test_a_handheld_party_plays_the_cheer_not_the_singing():
    """The picture is flat (a handheld pan reads as change everywhere) and the detector
    hears speech in the singing all along: the loudest moment is the candles going out."""
    loudness = [(float(i), db) for i, db in enumerate(CAKE_DB)]
    start = choose_window(
        _probes(62.8, (0.0, 62.8)), duration=62.8, hold=6.0, speech=CAKE_SPEECH, loudness=loudness
    )

    assert start <= 27.0 and start + 3.5 >= 28.0, "the cheer sits inside the hold that always plays"


def test_no_probes_keeps_the_opening():
    assert choose_window([], duration=30.0, hold=6.0) == pytest.approx(0.0)


def test_an_obstructed_second_is_avoided_between_two_equally_busy_windows():
    """#2022: among two windows with equal activity, the one with fewer flagged seconds
    wins."""
    probes = [
        (0.0, 0.1),
        (0.5, 0.1),
        (2.0, 3.0),
        (2.5, 3.0),
        (4.0, 3.0),
        (4.5, 3.0),
    ]

    clean = choose_window(probes, duration=8.0, hold=1.0, obstructed=[2.0, 2.5])

    assert 3.5 <= clean <= 4.5, "the flagged busy window must lose to the clean one"


def test_flagged_everywhere_keeps_todays_choice():
    """#2022: the penalty is the same for every window, so it changes nothing."""
    probes = _probes(12.24, (7.5, 9.5))
    every_second = [i * 0.5 for i in range(int(12.24 / 0.5) + 1)]

    with_flags = choose_window(probes, duration=12.24, hold=4.0, obstructed=every_second)
    without_flags = choose_window(probes, duration=12.24, hold=4.0)

    assert with_flags == without_flags


def test_the_real_planner_starts_each_kept_video_on_its_action(tmp_path):
    from dataclasses import replace

    from immich_memories.analysis.editorial_clip_facts import WindowFacts
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
        replace(
            _ports(),
            resolve_windows=lambda cs: place_windows(
                cs, lambda _id, _hold: WindowFacts(riders, (), None)
            ),
        ),
    ).plan

    videos = [c for c in plan["carriers"] if c["kind"] == "video"]
    assert videos
    for carrier in videos:
        assert carrier["start_time"] <= 7.5 <= 9.5 <= carrier["end_time"], "the riders cross"
        assert carrier["end_time"] - carrier["start_time"] == carrier["seconds"]
        assert carrier["end_time"] <= 12.0


def test_a_window_whose_action_sits_at_the_end_still_projects_from_the_real_source():
    """#2039: a video whose activity peaks right at its own end gets a window that runs to
    the clip's last playable frame. That window must stay inside the source and must still
    project; it must not raise ``editorial interval exceeds actual source metadata``."""
    from immich_memories.analysis.editorial_clip_facts import WindowFacts
    from immich_memories.analysis.editorial_source_route import project_source_rendering
    from immich_memories.analysis.editorial_structure_material import raw_centiseconds
    from immich_memories.analysis.editorial_video_windows import place_windows
    from immich_memories.config_loader import Config
    from tests.conftest import make_clip
    from tests.test_editorial_source_route import demand

    duration = 9.286
    raw = raw_centiseconds(duration)
    activity = _probes(duration, (duration - 1.0, duration))

    [carrier] = place_windows(
        [{"kind": "video", "asset_id": "video", "seconds": 4.0, "raw_seconds": raw}],
        lambda _id, _hold: WindowFacts(activity, (), None),
    )

    assert carrier["end_time"] <= duration

    _, rows = demand([make_clip("video", duration=duration)])
    projected = project_source_rendering([carrier], rows, config=Config(), include_live_photos=True)

    assert projected.plan.selections[0].end_time <= duration
