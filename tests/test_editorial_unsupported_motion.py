"""A motion sentence is evidence only where the companion's measured motion supports it (#1118).

The fixtures are generated: a flat "room" drawn in a few grey bands, and the same room with a
bright figure crossing it. The residual is the production optical-flow measurement run on them.
"""

from __future__ import annotations

import json

import pytest

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.analysis.editorial_motion_facts import measure_motion
from immich_memories.analysis.editorial_preparation_motion import (
    MOTION_PRODUCER,
    BankedMotionLines,
    missing_motion,
    motion_sources,
)
from immich_memories.analysis.editorial_structure_budget import RESIDUAL_MIN
from immich_memories.analysis.editorial_structure_lines import UnitLines
from immich_memories.store.motion_lines import (
    DESCRIBED,
    MotionLine,
    motion_line_row,
    remember_motion_lines,
)
from tests.annotation_rows import add_rows, annotation_store, read_rows
from tests.test_editorial_preparation_motion import Seat, answer, picture, produce, video


def companion(tmp_path, *, figure: bool) -> bytes:
    """Sixteen frames of an empty room; with `figure`, somebody walks across it."""
    import cv2
    import numpy as np

    path = tmp_path / ("figure.avi" if figure else "empty.avi")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 12, (160, 120))
    try:
        for index in range(16):
            frame = np.full((120, 160, 3), 180, dtype=np.uint8)
            frame[80:, :] = 120  # floor
            frame[55:85, 20:70] = 60  # sofa
            if figure:
                x = 50 + index * 6
                frame[30:110, x - 40 : x] = 230
                frame[50:70, x - 30 : x - 10] = 90
            writer.write(frame)
    finally:
        writer.release()
    return path.read_bytes()


@pytest.fixture
def store():
    return annotation_store()


def test_a_caption_claiming_action_in_an_empty_room_is_not_evidence_of_it(tmp_path, store):
    residual = measure_motion(companion(tmp_path, figure=False))["residual"]
    assert residual < RESIDUAL_MIN
    room = picture("room", live="room-companion")
    # A line an older pass banked for this picture, before this companion was measured.
    remember_motion_lines(
        store,
        [
            motion_line_row(
                asset_id="room",
                producer=MOTION_PRODUCER,
                source_digest=source_metadata_digest(room),
                line=MotionLine(DESCRIBED, "A woman dances across the living room.", 3),
                bytes_read=0,
            )
        ],
    )
    lines = BankedMotionLines(store=store, assets={"room": room}, described=True)
    text = UnitLines({"room": "2024-03-02 | An empty living room with a grey sofa."})
    live = {"asset_id": "room", "members": ["room"], "raw_seconds": 3.0, "favourite": False}
    unmeasured = live | {"kind": "live-motion", "residual": None, "motion_assessed": False}
    measured = live | {"kind": "live-still", "residual": residual, "motion_assessed": True}

    for unit in (unmeasured, measured):
        assert "dances" not in lines.observe(unit)
        assert not text.shows_life(unit)


def test_a_live_photo_whose_measured_action_differs_from_its_still_stays_usable(tmp_path, store):
    residual = measure_motion(companion(tmp_path, figure=True))["residual"]
    assert residual >= RESIDUAL_MIN
    swing = picture("swing", live="swing-companion")
    sources = motion_sources([swing], residual_of=lambda _asset: residual)
    produce(store, sources, seat=Seat(answer("A child runs in and jumps onto the swing.")))
    lines = BankedMotionLines(store=store, assets={"swing": swing}, described=True)
    text = UnitLines({"swing": "2024-03-02 | An empty swing in a garden."})
    unit = {
        "asset_id": "swing",
        "members": ["swing"],
        "raw_seconds": 3.0,
        "favourite": False,
        "kind": "live-motion",
        "residual": residual,
        "motion_assessed": True,
    }

    assert lines.observe(unit).startswith("A child runs in and jumps onto the swing.")
    assert text.shows_life(unit)


def test_a_prepared_line_records_the_evidence_that_admitted_it(store):
    from immich_memories.analysis.editorial_motion_facts import RESIDUAL_PRODUCER

    swing = picture("swing", live="swing-companion")
    sources = motion_sources(
        [swing, video("clip")], residual_of=lambda a: 2.1 if a.id == "swing" else None
    )
    produce(store, sources, seat=Seat(answer("A child runs.")))

    rows = {row["asset_id"]: row["provenance"] for row in read_rows(store, "motion_lines")}
    live, clip = json.loads(rows["swing"]), json.loads(rows["clip"])
    assert live["admitted_on"] == {"residual": 2.1, "producer": RESIDUAL_PRODUCER}
    assert clip["admitted_on"] == {"kind": "video"}
    assert live["keyframes_at"] == [1.0, 4.0, 7.0]
    assert live["prompt"] == clip["prompt"] != ""


def test_a_line_banked_before_provenance_is_counted_when_it_is_used(store):
    clip = video("clip")
    # A row exactly as the first motion producer wrote it, before provenance existed: no value
    # for that column at all, rather than a later producer's explicit NULL.
    add_rows(
        store,
        "motion_lines",
        {
            "asset_id": "clip",
            "producer": MOTION_PRODUCER,
            "source_digest": source_metadata_digest(clip),
            "status": DESCRIBED,
            "text": "A dog runs.",
            "frames": 3,
            "bytes_read": 0,
        },
    )
    lines = BankedMotionLines(store=store, assets={"clip": clip}, described=True)

    # Read-only, before any preparation recorded provenance: the old line still answers.
    assert lines.observe({"asset_id": "clip", "kind": "video"}).startswith("A dog runs.")
    assert lines.metrics()["unrecorded"] == 1

    produce_into = motion_sources([video("fresh")], residual_of=lambda _a: None)
    assert [s.asset_id for s in missing_motion(store, produce_into)] == ["fresh"]
    produce(store, produce_into, seat=Seat(answer("A cat jumps.")))
    fresh = BankedMotionLines(store=store, assets={"fresh": video("fresh")}, described=True)
    assert fresh.observe({"asset_id": "fresh", "kind": "video"}).startswith("A cat jumps.")
    assert fresh.metrics()["unrecorded"] == 0
