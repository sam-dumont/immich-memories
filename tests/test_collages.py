"""A collage never opens a film, and is left out when its day holds the pictures it repeats (#2773).

A multi-person film opened on a phone app's collage: four near-identical frames of one moment
tiled on a white page, the frames themselves in the library beside it. The tiles' soft studio
backdrop gave the gutter check no texture beside its gutters, so the page read as a photograph.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import numpy as np
from PIL import Image

from immich_memories.analysis.corpus.collages import (
    REPEATS_ITS_DAY,
    WOULD_OPEN,
    collage_exclusions,
)
from immich_memories.analysis.corpus.forwarded_checks import looks_composed
from immich_memories.api.models import Asset, AssetType, ExifInfo, Person

MORNING = datetime(2030, 3, 2, 10, 0, tzinfo=UTC)


def framed_grid_jpeg(rows: int = 2, cols: int = 2, *, size: int = 1340) -> bytes:
    """Near-identical frames of one moment on a white page: a border, uniform gutters, and tiles
    whose backdrop is a soft gradient with the subject in the middle."""
    margin, gutter = 64, 32
    rng = np.random.default_rng(7)
    page = np.full((size, size, 3), 255, dtype=np.uint8)
    tile_h = (size - 2 * margin - (rows - 1) * gutter) // rows
    tile_w = (size - 2 * margin - (cols - 1) * gutter) // cols
    yy, xx = np.mgrid[0:tile_h, 0:tile_w]
    backdrop = np.stack([215 - 20 * yy / tile_h, 185 - 15 * xx / tile_w, 190 + 0 * xx], axis=-1)
    for row in range(rows):
        for col in range(cols):
            tile = backdrop.copy()
            subject = ((yy - tile_h * (0.55 + 0.03 * row)) / (tile_h * 0.3)) ** 2 + (
                (xx - tile_w * (0.5 + 0.03 * col)) / (tile_w * 0.28)
            ) ** 2 < 1
            tile[subject] = rng.integers(40, 200, size=(int(subject.sum()), 3))
            top, left = margin + row * (tile_h + gutter), margin + col * (tile_w + gutter)
            page[top : top + tile_h, left : left + tile_w] = tile.astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(page).save(out, format="JPEG", quality=90)
    return out.getvalue()


def _picture(asset_id: str, at: datetime, *, people=("person-a",), camera: bool = True) -> Asset:
    return Asset(
        id=asset_id,
        type=AssetType.IMAGE,
        fileCreatedAt=at,
        fileModifiedAt=at,
        updatedAt=at,
        originalFileName=f"{asset_id}.jpg",
        exifInfo=ExifInfo(exposureTime="1/125") if camera else None,
        people=[Person(id=person, name=person) for person in people],
    )


def _pool(*pictures: Asset) -> dict[str, Asset]:
    return {picture.id: picture for picture in pictures}


def _composed_ids(*collages: str):
    page = framed_grid_jpeg()
    photo = io.BytesIO()
    Image.fromarray(np.random.default_rng(3).integers(0, 255, (400, 600, 3), dtype=np.uint8)).save(
        photo, format="JPEG"
    )
    previews = {}

    def composed(asset_id: str) -> bool:
        previews[asset_id] = page if asset_id in collages else photo.getvalue()
        return looks_composed(previews[asset_id])

    return composed, previews


def test_a_framed_grid_of_near_identical_frames_reads_as_composed():
    assert looks_composed(framed_grid_jpeg())
    assert looks_composed(framed_grid_jpeg(rows=3, cols=2))


def test_a_collage_whose_day_holds_its_frames_is_left_out():
    pool = _pool(
        _picture("frame-1", MORNING),
        _picture("frame-2", MORNING + timedelta(seconds=20)),
        _picture("collage", MORNING + timedelta(hours=1), camera=False),
    )
    composed, _previews = _composed_ids("collage")

    assert collage_exclusions(pool, pool, composed=composed) == {"collage": REPEATS_ITS_DAY}


def test_a_collage_alone_on_its_day_stays_an_ordinary_shot():
    pool = _pool(
        _picture("earlier", MORNING - timedelta(days=3)),
        _picture("collage", MORNING, camera=False),
        _picture("other-people", MORNING + timedelta(hours=1), people=("person-b",)),
    )
    composed, _previews = _composed_ids("collage")

    assert collage_exclusions(pool, pool, composed=composed) == {}


def test_a_collage_nothing_comes_before_never_opens_the_film():
    pool = _pool(
        _picture("collage", MORNING, camera=False),
        _picture("later", MORNING + timedelta(days=3)),
    )
    composed, _previews = _composed_ids("collage")

    assert collage_exclusions(pool, pool, composed=composed) == {"collage": WOULD_OPEN}


def test_a_camera_photograph_is_never_read_for_tiles():
    pool = _pool(_picture("camera", MORNING), _picture("made", MORNING, camera=False))
    composed, previews = _composed_ids()

    assert collage_exclusions(pool, pool, composed=composed) == {}
    assert set(previews) == {"made"}


def test_the_film_plan_leaves_out_a_collage_of_its_own_moment(tmp_path):
    from datetime import date

    from immich_memories.analysis.film.contract import StructurePlannerPorts
    from immich_memories.analysis.structure.planner import plan_structure
    from tests.editorial_film_fixtures import Day, FilmJudge, film_source

    source = film_source(
        tmp_path,
        [Day(date(2030, 3, 2), "A visit", moments=2)],
        seconds=60,
        span=(date(2030, 3, 1), date(2030, 3, 31)),
        pictures=3,
    )
    collage = "d000-m0-p0"
    plan = plan_structure(
        source,
        StructurePlannerPorts(
            # WHY: the reader is the boundary; it weighs the one day.
            judge=FilmJudge(weigh=lambda _row: "major"),
            thumbnail_hash=lambda _asset: None,
            composed=lambda asset_id: asset_id == collage,
        ),
    ).plan

    kept = {carrier["asset_id"] for carrier in plan["carriers"]}
    assert kept
    assert collage not in kept


def test_the_runtime_reads_each_preview_once_for_the_collage_check():
    from immich_memories.analysis.corpus.collages import preview_collage_check

    reads: list[str] = []
    page = framed_grid_jpeg()

    def read_preview(asset_id: str) -> bytes | None:
        reads.append(asset_id)
        return page if asset_id == "collage" else None

    composed = preview_collage_check(read_preview)

    assert composed("collage") and composed("collage")
    assert not composed("no-preview")
    assert reads == ["collage", "no-preview"]
