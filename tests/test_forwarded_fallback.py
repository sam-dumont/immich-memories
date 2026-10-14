"""Forwarded copies stand in where a film is short of its own pictures, when asked (opt-in).

A birthdays film's earlier birthdays held only pictures somebody sent: messaging exports with no
camera behind them, which every film refuses (`film_may_use`). With
`analysis.forwarded_copies_when_short` on, such copies become candidates on the days a short
part of the film holds no camera picture of its own, and then pass every check a camera
picture does. Off, nothing changes. They never stand in beside a camera picture of their day.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from immich_memories.analysis.forwarded_fallback import CopyChecks, stand_in_copies
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.api.models import Person
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange
from tests.test_editorial_source_route import photo

YEARS = (2022, 2023, 2024)


def _collage_jpeg() -> bytes:
    """Six photos tiled on a white page under a text band, as a phone's collage app lays them."""
    import io

    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(7)
    page = np.full((800, 600, 3), 250, dtype=np.uint8)
    page[30:60, 200:400] = 40  # the title's text
    for row in range(3):
        for col in range(2):
            top, left = 90 + row * 235, 10 + col * 295
            page[top : top + 225, left : left + 285] = rng.integers(20, 230, (225, 285, 3))
    out = io.BytesIO()
    Image.fromarray(page).save(out, format="JPEG", quality=90)
    return out.getvalue()


def _window(year: int) -> DateRange:
    start = datetime(year, 2, 1, tzinfo=UTC)
    return DateRange(start, start.replace(hour=23, minute=59, second=59))


WINDOWS = tuple(_window(year) for year in YEARS)


def _camera(key: str, at: datetime, *, starred: bool = True):
    picture = photo(key, at=at)
    picture.is_favorite = starred
    return picture


def _forwarded(key: str, at: datetime, *, person: bool = True):
    """A messaging export: a UUID JPEG, no camera, 1200x1600, of Kit when `person`."""
    picture = photo(key, at=at)
    picture.original_file_name = f"{abs(hash(key)) % 10**8:08d}-1111-2222-3333-444444444444.jpg"
    picture.exif_info = None
    picture.width, picture.height = 1200, 1600
    picture.people = [Person(id="person-kit", name="Kit")] if person else []
    return picture


def _config(tmp_path, *, on: bool) -> Config:
    config = Config(
        cache={"directory": str(tmp_path / "cache")},
        analysis={"forwarded_copies_when_short": on},
    )
    config.editorial.preparation.tier = "metadata_only"
    return config


def _library(*, copies_of_kit: bool = True, copy_beside_camera: bool = False) -> list:
    """2022 and 2023 hold four camera pictures each; 2024 holds only forwarded copies."""
    pictures = [
        _camera(f"cam-{year}-{n}", _window(year).start + timedelta(hours=8 + n))
        for year in YEARS[:2]
        for n in range(4)
    ]
    pictures += [
        _forwarded(
            f"fwd-2024-{n}", _window(2024).start + timedelta(hours=9 + n), person=copies_of_kit
        )
        for n in range(2)
    ]
    if copy_beside_camera:
        pictures.append(_forwarded("fwd-2023", _window(2023).start + timedelta(hours=15)))
    return pictures


# ── which copies may stand in: the gaps in the camera timeline ──────────────────────────────


def _ids(stand_ins) -> set[str]:
    return set(stand_ins.ids)


def test_off_no_copy_stands_in(tmp_path):
    assert _ids(stand_in_copies(_library(), _config(tmp_path, on=False), windows=WINDOWS)) == set()


def test_on_a_year_of_only_forwarded_copies_takes_them_and_a_year_with_camera_pictures_does_not(
    tmp_path,
):
    stand_ins = stand_in_copies(
        _library(copy_beside_camera=True), _config(tmp_path, on=True), windows=WINDOWS
    )

    assert _ids(stand_ins) == {"fwd-2024-0", "fwd-2024-1"}


def test_a_screenshot_is_never_a_forwarded_copy(tmp_path):
    shot = _forwarded("shot", _window(2024).start + timedelta(hours=9))
    shot.original_file_name = "Screenshot 2024-02-01 at 09.00.00.png"

    assert _ids(stand_in_copies([shot], _config(tmp_path, on=True), windows=WINDOWS)) == set()


YEAR = (DateRange(datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 12, 31, 23, 59, tzinfo=UTC)),)


def _year_of_a_person() -> list:
    """Camera pictures on two days of January, June and December; copies everywhere else.

    The lockdown shape: March holds copies on five days and no camera picture, September one
    day of copies, and June copies on days beside its camera pictures.
    """
    pictures = [
        _camera(f"cam-{month}-{day}", datetime(2020, month, day, 12, tzinfo=UTC))
        for month in (1, 6, 12)
        for day in (3, 17)
    ]
    pictures += [
        _forwarded(f"fwd-03-{day:02d}", datetime(2020, 3, day, 12, tzinfo=UTC))
        for day in (2, 5, 9, 14, 20)
    ]
    pictures += [_forwarded("fwd-03-09-b", datetime(2020, 3, 9, 18, tzinfo=UTC))]
    pictures += [_forwarded("fwd-09-12", datetime(2020, 9, 12, 12, tzinfo=UTC))]
    pictures += [_forwarded("fwd-06-10", datetime(2020, 6, 10, 12, tzinfo=UTC))]
    return pictures


def test_copies_fill_the_months_with_no_camera_picture_and_no_other(tmp_path):
    ids = _ids(stand_in_copies(_year_of_a_person(), _config(tmp_path, on=True), windows=YEAR))

    assert "fwd-09-12" in ids
    # June has camera pictures of its own: a copy beside them fills no gap.
    assert "fwd-06-10" not in ids


def test_a_gap_takes_the_share_a_month_with_camera_pictures_gets_not_a_flood(tmp_path):
    ids = _ids(stand_in_copies(_year_of_a_person(), _config(tmp_path, on=True), windows=YEAR))

    march = {asset.split("-")[2] for asset in ids if asset.startswith("fwd-03-")}
    # A month with camera pictures holds them on two days: March's copies get two days too,
    # the one with most copies first.
    assert len(march) == 2 and "09" in march


# ── which copies are no picture of this life, or a picture the library already holds ───────


def test_a_collage_is_refused_and_says_why(tmp_path):
    collage = _forwarded("fwd-2024-0", _window(2024).start + timedelta(hours=9))

    stand_ins = stand_in_copies(
        [collage],
        _config(tmp_path, on=True),
        windows=WINDOWS,
        checks=CopyChecks(preview_of=lambda _asset: _collage_jpeg()),
    )

    assert _ids(stand_ins) == set()
    assert "collage" in stand_ins.refused["fwd-2024-0"]


def test_a_copy_of_a_picture_the_library_holds_gives_way_to_the_original(tmp_path):
    copy = _forwarded("fwd-2024-0", _window(2024).start + timedelta(hours=9))
    # The original was shot weeks before the copy was received, outside every window.
    original = _camera("cam-original", datetime(2024, 1, 10, 12, tzinfo=UTC))
    hashes = {"fwd-2024-0": "f0f0f0f0f0f0f0f0", "cam-original": "f0f0f0f0f0f0f0f1"}

    stand_ins = stand_in_copies(
        [copy],
        _config(tmp_path, on=True),
        windows=WINDOWS,
        checks=CopyChecks(hash_of=hashes.get, originals=(original,)),
    )

    assert _ids(stand_ins) == set()
    assert "cam-original" in stand_ins.refused["fwd-2024-0"]


def test_a_copy_immich_groups_with_another_file_gives_way_whenever_that_file_was_shot(tmp_path):
    """The throwback: a re-shared photo of years ago arrives dated today. Immich's duplicate
    groups span the whole library, so its original is found wherever it sits in time."""
    copy = _forwarded("fwd-2024-0", _window(2024).start + timedelta(hours=9))

    stand_ins = stand_in_copies(
        [copy],
        _config(tmp_path, on=True),
        windows=WINDOWS,
        checks=CopyChecks(duplicate_groups=lambda: [("cam-2014", "fwd-2024-0")]),
    )

    assert _ids(stand_ins) == set()
    assert "cam-2014" in stand_ins.refused["fwd-2024-0"]


def test_a_copy_unlike_any_original_still_stands_in(tmp_path):
    copy = _forwarded("fwd-2024-0", _window(2024).start + timedelta(hours=9))
    original = _camera("cam-other", datetime(2024, 1, 10, 12, tzinfo=UTC))
    hashes = {"fwd-2024-0": "f0f0f0f0f0f0f0f0", "cam-other": "0f0f0f0f0f0f0f0f"}

    stand_ins = stand_in_copies(
        [copy],
        _config(tmp_path, on=True),
        windows=WINDOWS,
        checks=CopyChecks(hash_of=hashes.get, originals=(original,)),
    )

    assert _ids(stand_ins) == {"fwd-2024-0"}


def test_admission_takes_only_the_copies_named_to_stand_in():
    copy_2024 = _forwarded("fwd-2024", _window(2024).start + timedelta(hours=9))
    copy_2023 = _forwarded("fwd-2023", _window(2023).start + timedelta(hours=9))

    prepared = prepare_editorial_source(
        EditorialSelectionRequest(SourceScope(forwarded_stand_ins=(copy_2024.id,)), ()),
        EditorialDependencies(source_fetcher=lambda _: [copy_2024, copy_2023]),
    )

    assert set(prepared.candidate_ids) == {copy_2024.id}


# ── a film's cut, through every check ───────────────────────────────────────────────────────


def _cut(tmp_path, library, *, on: bool):
    """The rules route's cut of an on-this-day film over the three years, and its plan."""
    from immich_memories.analysis.editorial_pool import EditorialSourcePool
    from immich_memories.analysis.editorial_runtime import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
    from immich_memories.analysis.smart_pipeline import SmartPipeline
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from tests.test_editorial_rule_reader import _distinct_preview

    config = _config(tmp_path, on=on)
    # What the CLI hands the run: the copies that may stand in.
    stand_ins = stand_in_copies(library, config, windows=WINDOWS)
    planner = build_editorial_planner(
        source_pool=EditorialSourcePool(tuple(library)),
        # WHY: Immich, read only for a recognised person's face boxes; none are needed here.
        client=SimpleNamespace(get_asset_faces=lambda *_args, **_kwargs: []),
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "thumbnails"),
        context=EditorialRunContext(
            "fallback",
            "1 February",
            "on_this_day",
            WINDOWS,
            60,
            tmp_path / "artifacts",
            forwarded_stand_ins=tuple(sorted(stand_ins.ids)),
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_preview=lambda _client, key: _distinct_preview(key),
        ),
    )
    _, result = SmartPipeline(planner=planner).run_editorial_source(library)
    plan = json.loads((planner.last_attempt_directory / "plan.private.json").read_text())
    return {clip.asset.id for clip in result.selected_clips}, plan


def test_off_the_film_is_as_it_was(tmp_path):
    cut, _plan = _cut(tmp_path, _library(), on=False)

    assert not [asset for asset in cut if asset.startswith("fwd-")]


def test_on_a_year_of_only_forwarded_copies_gets_its_shot_and_says_where_it_came_from(tmp_path):
    cut, plan = _cut(tmp_path, _library(), on=True)

    assert any(asset.startswith("fwd-2024") for asset in cut), cut
    reasons = [c["why"] for c in plan["carriers"] if c["asset_id"].startswith("fwd-")]
    assert reasons and all("forwarded copy" in why for why in reasons), reasons


def test_on_a_forwarded_copy_that_does_not_stand_is_not_used(tmp_path):
    cut, _plan = _cut(tmp_path, _library(copies_of_kit=False), on=True)

    assert not [asset for asset in cut if asset.startswith("fwd-")]


def test_on_a_year_with_camera_pictures_uses_none_of_its_forwarded_copies(tmp_path):
    cut, _plan = _cut(tmp_path, _library(copy_beside_camera=True), on=True)

    assert "fwd-2023" not in cut


def test_a_copy_whose_caption_says_it_was_made_is_refused_and_a_camera_picture_is_not(tmp_path):
    """A composite (a child cut out onto a glitter background) has no gutters to see; where the
    run has captions, the caption names it."""
    from immich_memories.analysis.editorial_structure_material import source_exclusions

    copy = _forwarded("fwd", _window(2024).start + timedelta(hours=9))
    camera = _camera("cam", _window(2024).start + timedelta(hours=10), starred=False)
    caption = "A child superimposed on a glitter background"
    source = SimpleNamespace(
        assets={copy.id: copy, camera.id: camera},
        config=_config(tmp_path, on=True),
        audience_annotations={},
        owner_required_asset_ids=(),
    )

    refused = source_exclusions(
        source,
        SimpleNamespace(document_ocr_text=None),
        {copy.id: caption, camera.id: caption},
    )

    assert "superimposed" in refused[copy.id]
    assert camera.id not in refused
