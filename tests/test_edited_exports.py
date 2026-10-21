"""A video its metadata calls an edited export is demoted, never refused (#2783).

A track day's film spent half its shots on two exports from a lap-timing app: a dash-cam frame
with a speedometer and a lap map burnt in, named by the app and naming no camera, at the 12-second
hold real footage grows to. On a real library 1665 of 3201 make-less videos carry a name no
camera writes, and a few dozen of those are genuine clips somebody renamed, so the metadata is a
suspicion: a suspect ranks last in its moment, holds a beat, never opens the film, and keeps its
slot only when nothing else can fill it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from immich_memories.analysis.clips.budget import EDITED_EXPORT_HOLD_SECONDS
from immich_memories.analysis.clips.video_windows import grow_holds
from immich_memories.analysis.corpus.name_filter import edited_export_suspect
from immich_memories.analysis.film.material import UnitBuilder
from immich_memories.analysis.structure.finishing import (
    EXPORT_REPLACED,
    EXPORT_WOULD_OPEN,
    PlanRun,
    demote_edited_exports,
)
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from tests.conftest import make_asset
from tests.picture_fake import PictureFake

DAY = "2030-04-04"


def _video(name: str, *, make: str | None = None, starred: bool = False):
    return make_asset(
        "clip", original_file_name=name, exif_make=make, exif_model=None, is_favorite=starred
    )


@pytest.mark.parametrize(
    "name",
    [
        "01234567_CAR1_22222_20300404_130024.mp4",
        "lapapp.mp4",
        "Clip Ride 3 - 4K.mov",
        "1(2).mp4",
        "3f2a9c1e-5b7d-4e8f-a1b2-c3d4e5f60718.mp4",
        "MOVIE.m4v",
    ],
)
def test_a_make_less_video_with_an_app_name_is_a_suspect(name: str):
    assert edited_export_suspect(_video(name))


@pytest.mark.parametrize(
    "name",
    [
        "IMG_0229.MOV",
        "IMG_2222(1).MOV",
        "VID_20240616094327.mp4",
        "PXL_20240101_101010123.mp4",
        "MVI_7652.MP4",
        "GH010672.MP4",
        "GOPR0001.MP4",
        "DJI_0042.MP4",
        "20190407_111516.mp4",
        "2019_0419_095511_101.MP4",
        "trim.4F2A1C3E.MOV",
        "975A67EF-FF5D-4E5E-B043-D575A3618180.MOV",
    ],
)
def test_a_make_less_clip_with_a_camera_name_is_no_suspect(name: str):
    assert not edited_export_suspect(_video(name))


def test_a_star_or_a_camera_make_clears_the_suspicion():
    assert not edited_export_suspect(_video("lapapp.mp4", starred=True))
    assert not edited_export_suspect(_video("lapapp.mp4", make="Apple"))


def _builder(*assets) -> UnitBuilder:
    source = SimpleNamespace(
        assets={a.id: a for a in assets},
        motion_residuals={},
        clip_frames={},
        audience="family",
        companion_detectors={},
        speech_regions={},
        config=Config(),
        pixel_facts={a.id: (50.0, 118.0) for a in assets},
    )
    wall = SimpleNamespace(
        event_assets={"F01": [a.id for a in assets]},
        moment_of_asset=dict.fromkeys((a.id for a in assets), "M01"),
    )
    # WHY: ports are the planner's boundary to motion and hashing; none is read here.
    ports = SimpleNamespace(
        resolve_motion=None, live_source_integrity=None, thumbnail_hash=lambda _a: None, rules=None
    )
    return UnitBuilder(source, ports, wall, renderings={}, never_auto=set(), document_sources={})


def _clip(asset_id: str, name: str) -> PictureFake:
    return PictureFake(
        id=asset_id,
        is_favorite=False,
        people=[],
        faces=[],
        duration_seconds=290.0,
        type=AssetType.VIDEO,
        original_file_name=name,
        exif_info=None,
        file_created_at=datetime(2030, 4, 4, 10, 0, tzinfo=UTC),
    )


def test_a_suspect_ranks_below_real_footage_and_holds_a_beat():
    builder = _builder(_clip("export", "lapapp.mp4"), _clip("phone", "IMG_0080.MOV"))

    assert builder.quality("export") < builder.quality("phone")
    units = {u["asset_id"]: u for u in builder.units_of("F01")}
    assert units["export"]["seconds"] == EDITED_EXPORT_HOLD_SECONDS
    assert units["export"]["hold_cap"] == EDITED_EXPORT_HOLD_SECONDS
    assert "hold_cap" not in units["phone"]


def test_a_spare_film_never_grows_a_suspect_past_its_beat():
    shots = [
        {
            "asset_id": "export",
            "kind": "video",
            "seconds": 3.5,
            "raw_seconds": 290.0,
            "taken": f"{DAY}T10:00:00",
            "hold_cap": EDITED_EXPORT_HOLD_SECONDS,
        },
        {
            "asset_id": "phone",
            "kind": "video",
            "seconds": 6.0,
            "raw_seconds": 30.0,
            "taken": f"{DAY}T10:10:00",
        },
    ]

    grown = {c["asset_id"]: c["seconds"] for c in grow_holds(shots, 30.0)}

    assert grown["export"] == EDITED_EXPORT_HOLD_SECONDS
    assert grown["phone"] == 12.0


def _shot(asset_id: str, minute: int, **extra) -> dict:
    return {
        "asset_id": asset_id,
        "taken": f"{DAY}T10:{minute:02d}:00+00:00",
        "kind": "video",
        "members": [asset_id],
        "seconds": 3.5,
        "story_episode": "S001",
        "moment": "M001",
    } | extra


EXPORT = {"edited_export": True, "hold_cap": EDITED_EXPORT_HOLD_SECONDS}
# WHY: ports are the planner's boundary to motion resolution, which no shot here needs.
PORTS = SimpleNamespace(resolve_motion=None)


def _demote(carriers: list[dict], offers: list[dict]) -> PlanRun:
    run = PlanRun(carriers=carriers, final_content_cap=0.0)
    demote_edited_exports(
        run,
        PORTS,
        replacements_for=lambda _c: [("moment", o) for o in offers],
        admits=lambda _row, _cut: True,
    )
    return run


def test_real_footage_of_its_moment_takes_a_suspects_slot():
    run = _demote(
        [_shot("opening", 0), _shot("export", 5, **EXPORT), _shot("closing", 9)],
        [_shot("phone", 6)],
    )

    assert [c["asset_id"] for c in run.carriers] == ["opening", "phone", "closing"]
    assert [(c["asset_id"], c["reason"]) for c in run.cut_carriers] == [("export", EXPORT_REPLACED)]


def test_a_suspect_is_never_traded_for_another_suspect():
    run = _demote(
        [_shot("opening", 0), _shot("export", 5, **EXPORT)],
        [_shot("other-export", 6, **EXPORT)],
    )

    assert [c["asset_id"] for c in run.carriers] == ["opening", "export"]


def test_a_suspect_never_opens_the_film():
    run = _demote([_shot("export", 0, **EXPORT), _shot("phone", 5)], [])

    assert [c["asset_id"] for c in run.carriers] == ["phone"]
    assert [(c["asset_id"], c["reason"]) for c in run.cut_carriers] == [
        ("export", EXPORT_WOULD_OPEN)
    ]


def test_a_day_with_nothing_else_still_keeps_its_suspect():
    run = _demote([_shot("export", 0, **EXPORT)], [])

    assert [c["asset_id"] for c in run.carriers] == ["export"]


def test_a_starred_export_is_the_owners_answer():
    run = _demote(
        [_shot("export", 0, favourite=True, **EXPORT), _shot("phone", 5)], [_shot("other", 1)]
    )

    assert [c["asset_id"] for c in run.carriers] == ["export", "phone"]
