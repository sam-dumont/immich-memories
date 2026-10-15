"""A Live Photo the owner adds in review is stitched with its neighbours and held to the floor.

It plays as motion when the clip it would play (the stitch of nearby Live Photos, else its own
clip) lasts the motion floor and moves; otherwise it plays as its still (#2453).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from immich_memories.analysis.clips.added_live_motion import added_live_motion
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from tests.conftest import make_asset

NOON = datetime(2026, 9, 24, 12, tzinfo=UTC)
TIGHT_TRIPLE = [(-1.65, 2.44), (-0.81, 1.932), (0.0, 1.213)]


def _pictures(shots):
    """Live stills at the given offsets, with their companions of the given lengths."""
    stills, companions = [], {}
    for index, (offset, seconds) in enumerate(shots):
        still = make_asset(
            f"still-{index}", duration=None, file_created_at=NOON + timedelta(seconds=offset)
        )
        still.type = AssetType.IMAGE
        still.live_photo_video_id = f"clip-{index}"
        companions[still.live_photo_video_id] = make_asset(
            still.live_photo_video_id, duration=seconds
        )
        stills.append(still)
    return stills, companions


def _decide(shots, added_index, *, residual=9.0, offsets="measured", other=()):
    stills, companions = _pictures(shots)
    shutters = {s.live_photo_video_id: s.file_created_at.timestamp() for s in stills}
    asked: list[str] = []

    def measured(_companions):
        if offsets == "refused":
            return lambda ids: [None] * (len(ids) - 1)
        return lambda ids: [shutters[b] - shutters[a] for a, b in pairwise(ids)]

    def moving(video_id):
        asked.append(video_id)
        return residual

    rendering = added_live_motion(
        stills[added_index],
        Config(),
        nearby=lambda _asset: [*stills, *other],
        companion=companions.get,
        clock_offsets=measured,
        residual=moving,
    )
    return rendering, asked


def test_an_added_lone_clip_that_lasts_the_floor_and_moves_plays():
    rendering, asked = _decide([(0.0, 2.867)], 0)

    assert rendering is not None
    assert rendering.video_ids == ("clip-0",)
    assert asked == ["clip-0"]


def test_an_added_lone_clip_under_the_floor_is_its_still():
    rendering, asked = _decide([(0.0, 1.213)], 0)

    assert rendering is None
    assert asked == [], "nothing is measured for a clip that may not play"


def test_an_added_picture_stitches_with_its_nearby_live_photos():
    rendering, _ = _decide(TIGHT_TRIPLE, 2)

    assert rendering is not None
    assert len(rendering.video_ids) == 3
    assert "still-2" in rendering.still_ids
    assert rendering.duration_seconds >= 2.5


def test_an_added_picture_whose_joins_refuse_and_own_clip_is_short_is_its_still():
    rendering, _ = _decide(TIGHT_TRIPLE, 2, offsets="refused")

    assert rendering is None


def test_an_added_picture_whose_joins_refuse_plays_an_own_clip_that_lasts_the_floor():
    rendering, _ = _decide([(0.0, 2.867), (1.62, 2.867)], 0, offsets="refused")

    assert rendering is not None
    assert rendering.video_ids == ("clip-0",)


def test_an_added_stitch_that_barely_moves_is_its_still():
    rendering, _ = _decide(TIGHT_TRIPLE, 2, residual=0.4)

    assert rendering is None


def test_a_neighbour_without_a_companion_or_a_plain_photo_is_left_out():
    plain = make_asset("plain", duration=None, file_created_at=NOON)
    plain.type = AssetType.IMAGE
    rendering, _ = _decide([(0.0, 2.867)], 0, other=(plain,))

    assert rendering is not None
    assert rendering.still_ids == ("still-0",)


class _Immich:
    """WHY: Immich is the boundary: the photos around a picture, a video's metadata and bytes."""

    def __init__(self, stills, companions):
        self.stills, self.companions = stills, companions
        self.ranges = []

    def get_photos_for_date_range(self, date_range):
        self.ranges.append(date_range)
        return [s for s in self.stills if date_range.start <= s.file_created_at <= date_range.end]

    def get_asset(self, asset_id):
        return self.companions[asset_id]

    def get_video_playback(self, asset_id):
        return b"playback of " + asset_id.encode()


def _saved_cut_stitch(monkeypatch, shots, residual):
    from immich_memories.analysis.clips import motion_facts as editorial_motion_facts
    from immich_memories.generate_saved_cut import _live_motion

    stills, companions = _pictures(shots)
    immich = _Immich(stills, companions)
    # WHY: optical flow needs decoded frames of a real clip; the residual is the input here.
    monkeypatch.setattr(
        editorial_motion_facts, "measure_motion", lambda _payload: {"residual": residual}
    )
    return _live_motion(Config(), immich)(stills[0]), immich


def test_a_saved_cut_plays_an_added_live_photo_that_lasts_the_floor_and_moves(monkeypatch):
    rendering, immich = _saved_cut_stitch(monkeypatch, [(0.0, 2.867)], residual=3.0)

    assert rendering is not None
    assert immich.ranges, "the neighbours were looked up"


def test_a_saved_cut_holds_an_added_live_photo_whose_clip_barely_moves(monkeypatch):
    rendering, _ = _saved_cut_stitch(monkeypatch, [(0.0, 2.867)], residual=0.4)

    assert rendering is None
