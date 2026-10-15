"""A Live Photo plays as motion only from a clip that lasts the motion floor and moves (#2453).

The clip is a stitch of nearby Live Photos when their joins measure, or one Live Photo's own
clip. Either way it plays only when it lasts `MIN_LIVE_MOTION_SECONDS` (2.5 s) and passes the
motion discriminant; anything shorter is half a sentence and plays as its still.

The September cases are synthetic stand-ins for three shots of a real monthly film: an ordinary
3.07 s video, a lone Live Photo's 2.87 s clip, and the favourite of three tight shots whose own
clip ran 1.21 s.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

import pytest

from immich_memories.analysis.clips.motion_rendering import motion_renderings
from immich_memories.analysis.corpus.trace import ClipStory
from immich_memories.analysis.film.material import (
    build_material,
    read_wall,
    rules_still_seconds,
)
from immich_memories.analysis.structure.planner import plan_structure
from immich_memories.api.models import AssetType
from immich_memories.cli._runs_reading import why_text
from immich_memories.config.loader import Config
from immich_memories.generate_downloads import _try_merge_burst, download_clip
from immich_memories.operations.storyboard import storyboard_from_plan, storyboard_lines
from immich_memories.processing.download_coordinator import DownloadResult
from immich_memories.processing.live_material import MIN_LIVE_MOTION_SECONDS
from immich_memories.processing.preparation_fallbacks import watching_fallbacks
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset, make_clip
from tests.test_editorial_duration_planner_integration import source
from tests.test_live_clock_offsets_on_demand import live_carriers, ports

# One Live burst per entry, an hour apart: (shutter offset s, companion clip s) per picture.
LONE_LIKED = [(0.0, 2.867)]
LONE_SHORT = [(0.0, 1.213)]
# Three shots within 1.65 s; the starred last one's own clip runs 1.213 s.
TIGHT_TRIPLE = [(-1.65, 2.44), (-0.81, 1.932), (0.0, 1.213)]
PAIR = [(0.0, 2.867), (1.62, 2.867)]


def library(tmp_path, bursts, *, residual=9.0, starred_last=False):
    """The given bursts, an hour apart, each picture a Live Photo with its own companion."""
    captured = source(tmp_path, seconds=15, pictures=sum(len(b) for b in bursts))
    assets = dict(captured.assets)
    ordered = sorted(assets.values(), key=lambda asset: asset.file_created_at)
    start = ordered[0].file_created_at
    durations, shutters = {}, {}
    pictures = iter(ordered)
    for hour, burst in enumerate(bursts):
        for member, (offset, seconds) in enumerate(burst):
            asset = next(pictures)
            asset.file_created_at = start + timedelta(hours=hour, seconds=5 + offset)
            asset.live_photo_video_id = f"video-{asset.id}"
            asset.is_favorite = starred_last and member == len(burst) - 1
            durations[asset.live_photo_video_id] = seconds
            shutters[asset.live_photo_video_id] = asset.file_created_at.timestamp()
    captured = replace(
        captured,
        assets=assets,
        companion_assets={
            video: make_asset(video, duration=seconds) for video, seconds in durations.items()
        },
        motion_residuals={key: {"residual": residual} for key in assets},
        store=annotation_store(),
    )
    return captured, shutters


def true_gaps(shutters):
    """A measurement that finds each join at the true gap between its two shutters."""

    def offsets(video_ids):
        return [shutters[b] - shutters[a] for a, b in pairwise(video_ids)]

    return offsets


def refusing(video_ids):
    return [None] * (len(video_ids) - 1)


def is_still_hold(captured, seconds: float) -> bool:
    """A hold a still gets: between the rules reader's shortest and the longest still hold."""
    nominal = captured.config.photos.duration
    shortest = rules_still_seconds(favourite=False, known_people=False, nominal=nominal)
    return shortest <= seconds <= nominal + 1.0


def the_rendering(captured, offsets):
    found = motion_renderings(
        list(captured.assets.values()),
        captured.config,
        companion_assets=captured.companion_assets,
        clock_offsets=offsets,
    )
    (rendering,) = {id(r): r for r in found.values()}.values()
    return rendering


def test_the_floor_is_two_and_a_half_seconds_and_the_config_default():
    assert MIN_LIVE_MOTION_SECONDS == 2.5
    assert Config().analysis.live_photo_min_clip_seconds == MIN_LIVE_MOTION_SECONDS


@pytest.mark.parametrize(
    ("burst", "plays"),
    [(LONE_LIKED, True), (LONE_SHORT, False), (PAIR, True), (TIGHT_TRIPLE, True)],
    ids=["lone-2.87s", "lone-1.21s", "pair", "tight-triple-3.48s"],
)
def test_a_clip_may_play_only_when_it_lasts_the_floor(tmp_path, burst, plays):
    captured, shutters = library(tmp_path, [burst])

    rendering = the_rendering(captured, true_gaps(shutters))

    assert rendering.may_play is plays
    assert (rendering.duration_seconds >= 2.5) is plays
    assert (rendering.still_reason is None) is plays


def test_a_short_clip_says_why_it_is_a_still(tmp_path):
    captured, shutters = library(tmp_path, [LONE_SHORT])

    reason = the_rendering(captured, true_gaps(shutters)).still_reason

    assert reason is not None
    assert "1.2 s" in reason and "2.5 s" in reason


def test_the_liked_lone_clip_plays_as_motion(tmp_path):
    captured, shutters = library(tmp_path, [LONE_LIKED])

    (carrier,) = live_carriers(plan_structure(captured, ports(true_gaps(shutters))).plan)

    assert carrier["kind"] == "live-motion"
    assert carrier["seconds"] == pytest.approx(2.86, abs=0.01)
    assert "live_note" not in carrier


def test_the_tight_triple_plays_as_one_stitch_when_its_joins_measure(tmp_path):
    captured, shutters = library(tmp_path, [TIGHT_TRIPLE], starred_last=True)

    (carrier,) = live_carriers(plan_structure(captured, ports(true_gaps(shutters))).plan)

    assert carrier["kind"] == "live-motion"
    assert len(carrier["video_ids"]) == 3
    # The measured joins place the stitch at ~2.9 s (metadata alone estimates 3.48 s).
    assert carrier["seconds"] >= MIN_LIVE_MOTION_SECONDS


def test_the_tight_triple_never_plays_its_short_own_clip_when_its_joins_refuse(tmp_path):
    """The joins refuse, so nothing is stitched; the starred picture's own 1.21 s clip is
    under the floor, so the picture is its still (the #1547 fallback played it)."""
    captured, _ = library(tmp_path, [TIGHT_TRIPLE], starred_last=True)

    (carrier,) = live_carriers(plan_structure(captured, ports(refusing)).plan)

    assert carrier["kind"] == "live-still"
    assert is_still_hold(captured, carrier["seconds"])
    assert carrier["live_note"]


def test_a_refused_burst_still_plays_an_own_clip_that_lasts_the_floor(tmp_path):
    captured, _ = library(tmp_path, [PAIR])

    (carrier,) = live_carriers(plan_structure(captured, ports(refusing)).plan)

    assert carrier["kind"] == "live-motion"
    assert len(carrier["video_ids"]) == 1
    assert carrier["seconds"] >= 2.5


def test_a_lone_short_clip_holds_its_still_for_a_photos_hold(tmp_path):
    captured, shutters = library(tmp_path, [LONE_SHORT])

    (carrier,) = live_carriers(plan_structure(captured, ports(true_gaps(shutters))).plan)

    assert carrier["kind"] == "live-still"
    assert carrier["motion_candidate"] is False
    assert is_still_hold(captured, carrier["seconds"])
    assert carrier["live_note"]


@pytest.mark.parametrize("burst", [LONE_LIKED, TIGHT_TRIPLE], ids=["lone", "stitch"])
def test_the_motion_discriminant_holds_a_clip_that_barely_moves(tmp_path, burst):
    captured, shutters = library(tmp_path, [burst], residual=0.4)

    (carrier,) = live_carriers(plan_structure(captured, ports(true_gaps(shutters))).plan)

    assert carrier["kind"] == "live-still"
    assert is_still_hold(captured, carrier["seconds"])


def test_an_ordinary_short_video_still_plays(tmp_path):
    captured, shutters = library(tmp_path, [LONE_SHORT])
    taken = next(iter(captured.assets.values())).file_created_at + timedelta(minutes=30)
    video = make_asset("ordinary-video", duration=3.068, file_created_at=taken)
    video.type = AssetType.VIDEO
    [moment] = captured.moment_asset_ids
    captured = replace(
        captured,
        assets={**captured.assets, video.id: video},
        moment_asset_ids={moment: (*captured.moment_asset_ids[moment], video.id)},
    )

    material = build_material(captured, ports(true_gaps(shutters)), read_wall(captured))

    units = [unit for units in material.units.values() for unit in units]
    played = next(unit for unit in units if unit["asset_id"] == video.id)
    assert played["kind"] == "video"
    assert played["seconds"] == pytest.approx(3.06, abs=0.01)
    held = next(unit for unit in units if unit["asset_id"] != video.id)
    assert held["kind"] == "live-still"


def test_runs_story_and_why_say_why_a_live_photo_held_its_still(tmp_path):
    captured, shutters = library(tmp_path, [LONE_SHORT])
    plan = plan_structure(captured, ports(true_gaps(shutters))).plan
    (carrier,) = live_carriers(plan)

    board = storyboard_from_plan(plan, None)
    shot = next(s for s in board.shots if s.asset_id == carrier["asset_id"])

    assert not shot.motion
    assert shot.seconds == carrier["seconds"]
    assert shot.note == carrier["live_note"]
    assert any(carrier["live_note"] in line for line in storyboard_lines(board))
    story = ClipStory(carrier["asset_id"], "", True, (), None, None)
    assert carrier["live_note"] in why_text(carrier["asset_id"], story, board, width=200)


# --- the render side: the clip that actually remains must last the floor, or the still ---

BURST = ["burst-1", "burst-2", "burst-3"]
SECOND_EACH = [(0.0, 1.0)] * 3  # 3.0 s whole, 2.0 s after losing one
SECOND_AND_A_HALF_EACH = [(0.0, 1.5)] * 3  # 4.5 s whole, 3.0 s after losing one


class _Immich:
    def __init__(self, failing=()):
        self.failing = failing
        self.asked: list[str] = []

    def download_asset(self, asset_id, destination, expected_size_bytes=None):
        self.asked.append(asset_id)
        if asset_id in self.failing:
            raise OSError("connection reset")
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"companion bytes")


def _burst_clip(trims, ids=BURST):
    clip = make_clip("live-1")
    clip.asset.type = AssetType.IMAGE
    clip.asset.live_photo_video_id = "companion-1"
    clip.live_burst_video_ids = list(ids)
    clip.live_burst_trim_points = list(trims)
    return clip


def _merges(monkeypatch) -> list[list[Path]]:
    calls: list[list[Path]] = []

    def merge(paths, trims, merged_path, **_kwargs):
        calls.append(list(paths))
        merged_path.write_bytes(b"merged")
        return merged_path

    # WHY: the FFmpeg merge is the boundary; these cases are about which components reach it.
    monkeypatch.setattr("immich_memories.generate_downloads._try_merge_burst", merge)
    return calls


def test_a_burst_left_under_the_floor_by_a_download_is_its_still(tmp_path, monkeypatch):
    merges = _merges(monkeypatch)
    immich = _Immich(failing=(BURST[0],))

    with watching_fallbacks() as noted:
        produced = download_clip(immich, None, _burst_clip(SECOND_EACH), tmp_path)

    assert produced is None
    assert merges == []
    # Never the unstitched companion either.
    assert "companion-1" not in immich.asked
    assert any("still" in note for note in noted)


def test_a_burst_that_still_lasts_the_floor_merges_what_remains(tmp_path, monkeypatch):
    merges = _merges(monkeypatch)

    produced = download_clip(
        _Immich(failing=(BURST[0],)), None, _burst_clip(SECOND_AND_A_HALF_EACH), tmp_path
    )

    assert produced is not None
    assert [len(paths) for paths in merges] == [2]


def test_a_burst_left_under_the_floor_by_a_prefetch_is_its_still(tmp_path, monkeypatch):
    merges = _merges(monkeypatch)
    good = tmp_path / "good.MOV"
    good.write_bytes(b"companion bytes")
    results = {
        BURST[0]: DownloadResult(BURST[0], BURST[0], None, "timed out"),
        BURST[1]: DownloadResult(BURST[1], BURST[1], good),
        BURST[2]: DownloadResult(BURST[2], BURST[2], good),
    }

    produced = download_clip(
        _Immich(), None, _burst_clip(SECOND_EACH), tmp_path, prefetched_burst_results=results
    )

    assert produced is None
    assert merges == []


def test_a_failed_merge_is_its_still_not_its_companion(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "immich_memories.generate_downloads._try_merge_burst", lambda *_a, **_k: None
    )
    immich = _Immich()

    assert download_clip(immich, None, _burst_clip(SECOND_EACH), tmp_path) is None
    assert "companion-1" not in immich.asked


def test_an_unreadable_component_leaving_too_short_a_clip_merges_nothing(tmp_path, monkeypatch):
    from immich_memories.processing import live_photo_merger

    paths = [tmp_path / f"{name}.MOV" for name in BURST]
    for path in paths:
        path.write_bytes(b"bytes")

    def readable(clip_paths, trims):
        return clip_paths[:2], trims[:2]

    def forbidden(*_args, **_kwargs):
        pytest.fail("a clip under the floor must never be merged into motion")

    # WHY: ffprobe is the boundary; the third component reads as unreadable.
    monkeypatch.setattr(live_photo_merger, "filter_valid_clips", readable)
    monkeypatch.setattr(live_photo_merger, "build_merge_command", forbidden)

    with watching_fallbacks() as noted:
        assert _try_merge_burst(paths, list(SECOND_EACH), tmp_path / "merged.mp4") is None
    assert noted


def _photo_render(tmp_path, monkeypatch) -> list[float | None]:
    from immich_memories.processing.assembly_config import AssemblyClip

    held: list[float | None] = []

    def render(clip, params, output_dir, *, duration_seconds=None):
        held.append(duration_seconds)
        return AssemblyClip(
            path=tmp_path / f"{clip.asset.id}.mp4",
            duration=params.config.photos.duration,
            asset_id=clip.asset.id,
            is_photo=True,
        )

    # WHY: the Ken Burns render is the boundary; the question is which path the picture takes.
    monkeypatch.setattr("immich_memories.generate_photos.render_photo_as_clip", render)
    return held


def _extract(tmp_path, clip, client):
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_clips import extract_clips

    config = Config()
    config.hardware.enabled = False
    params = GenerationParams(
        clips=[clip], output_path=tmp_path / "memory.mp4", config=config, client=client
    )
    return extract_clips(params, None, tmp_path), config


def test_a_planned_short_burst_renders_as_its_photo_without_downloading(tmp_path, monkeypatch):
    held = _photo_render(tmp_path, monkeypatch)
    immich = _Immich()

    result, config = _extract(tmp_path, _burst_clip(SECOND_EACH[:2], BURST[:2]), immich)

    assert held == [None]  # the configured photo hold, not the clip's length
    assert [clip.duration for clip in result] == [config.photos.duration]
    assert immich.asked == []


def test_a_burst_that_falls_short_at_render_plays_its_photo(tmp_path, monkeypatch):
    held = _photo_render(tmp_path, monkeypatch)
    _merges(monkeypatch)

    result, config = _extract(tmp_path, _burst_clip(SECOND_EACH), _Immich(failing=(BURST[1],)))

    assert held == [None]
    assert [clip.is_photo for clip in result] == [True]
    assert [clip.duration for clip in result] == [config.photos.duration]
