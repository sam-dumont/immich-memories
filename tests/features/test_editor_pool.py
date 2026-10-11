"""What the editor is handed, decided by the real Basic editor on records shaped as Immich sends them.

The fixture-library feature tests script selection, so the rules the editor applies to its pool
(folding copies, the owner's keep and leave-out choices) are checked here instead: the production
planner at the Basic tier (`metadata_only`, no model), fed Immich asset records, and asked which
pictures its cut keeps and what its decision log says about the others.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from immich_memories.api.models import Asset, MetadataSearchResult, Stack
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.timeperiod import DateRange
from tests.test_capture_local_time import FAR, _trips_of, cut, picture

MAY = DateRange(datetime(2024, 5, 1), datetime(2024, 5, 31, 23, 59, 59))


def _month() -> list[Asset]:
    """Twelve starred days of May, one picture each: the editor keeps every one of them."""
    return [picture(f"day-{n:02}", datetime(2024, 5, 2 + n, 12), favourite=True) for n in range(12)]


def _sha1(content: str) -> str:
    """A checksum as Immich stores it: the base64 of the file's SHA-1."""
    return base64.b64encode(hashlib.sha1(content.encode()).digest()).decode()  # noqa: S324


def _file(key: str, taken: datetime, name: str, *, modified: datetime | None = None) -> Asset:
    """A starred still with its file name, size and camera, the way a phone library holds it."""
    return picture(key, taken, favourite=True).model_copy(
        update={
            "original_file_name": name,
            "file_modified_at": modified or taken,
            "width": 4032,
            "height": 3024,
        }
    )


def _immich(stacks: list[Stack] | None = None):
    # WHY: the Immich read boundary (face boxes, OCR, server version, stacks); the autospec refuses
    # any call the real client would.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset_faces.return_value = []
    client.get_server_info.return_value = SimpleNamespace(major=3, minor=3, version_string="3.3.0")
    client.get_asset_ocr_text.return_value = None
    client.search_metadata.return_value = MetadataSearchResult()
    client.get_stacks.return_value = stacks or []
    return client


def _source_eligibility(tmp_path: Path) -> dict:
    """The editor's first pass, as its decision log (`runs why`) records it."""
    trace = json.loads(next(tmp_path.rglob("selection-trace.private.json")).read_text())
    return next(p for p in trace["editorial_passes"] if p["name"] == "source-eligibility")


@pytest.mark.feature("generate.copies-fold")
def test_identical_bytes_fold_into_one_picture_before_the_editor_sees_the_pool(tmp_path):
    shot = datetime(2024, 5, 20, 17)
    first = picture("copy-a", shot, favourite=True).model_copy(update={"checksum": _sha1("x")})
    second = picture("copy-b", shot, favourite=True).model_copy(update={"checksum": _sha1("x")})

    chosen, _ = cut(tmp_path, "custom", (MAY,), [*_month(), first, second], client=_immich())

    # Both starred, so both would play; one copy stands for both and the other never reaches
    # the editor's pool.
    assert "copy-a" in chosen
    assert "copy-b" not in chosen
    assert "copy-b" not in _source_eligibility(tmp_path)["input_ids"]


@pytest.mark.feature("generate.copies-fold")
def test_another_file_of_the_same_picture_folds_and_the_newest_full_size_file_plays(tmp_path):
    shot = datetime(2024, 5, 20, 17)
    original = _file("camera-file", shot, "IMG_7000.HEIC")
    later = _file("saved-again", shot, "IMG_7000.JPG", modified=shot + timedelta(days=3))

    chosen, _ = cut(tmp_path, "custom", (MAY,), [*_month(), original, later], client=_immich())
    rejected = {r["asset_id"]: r["reason"] for r in _source_eligibility(tmp_path)["rejected"]}

    assert "saved-again" in chosen
    assert "camera-file" not in chosen
    assert "another file of the same picture" in rejected["camera-file"]


@pytest.mark.feature("generate.copies-fold")
def test_an_immich_stack_folds_into_its_top_picture(tmp_path):
    shot = datetime(2024, 5, 20, 17)
    top = _file("stack-top", shot, "IMG_7001.HEIC")
    member = _file("stack-member", shot + timedelta(seconds=2), "IMG_7002.HEIC")
    stacks = [
        Stack(
            id="stack-1",
            primaryAssetId="stack-top",
            assets=[{"id": "stack-top"}, {"id": "stack-member"}],
        )
    ]

    chosen, _ = cut(tmp_path, "custom", (MAY,), [*_month(), top, member], client=_immich(stacks))
    rejected = {r["asset_id"]: r["reason"] for r in _source_eligibility(tmp_path)["rejected"]}

    assert "stack-top" in chosen
    assert "stack-member" not in chosen
    assert "another file of the same stack" in rejected["stack-member"]


@pytest.mark.feature("cut.include-exclude")
def test_the_editor_keeps_what_the_owner_includes_and_drops_what_they_exclude(tmp_path):
    """`--include` and `--exclude` reach the editor as the owner's required and excluded ids."""
    unstarred = picture("not-starred", datetime(2024, 5, 25, 9))
    month = _month()

    plain, _ = cut(tmp_path / "plain", "custom", (MAY,), [*month, unstarred], client=_immich())
    chosen, _ = cut(
        tmp_path / "owned",
        "custom",
        (MAY,),
        [*month, unstarred],
        client=_immich(),
        owner_required_asset_ids=("not-starred",),
        owner_excluded_asset_ids=("day-03",),
    )
    rejected = {
        r["asset_id"]: r["reason"] for r in _source_eligibility(tmp_path / "owned")["rejected"]
    }

    # Left alone, the editor keeps the starred day and drops the unstarred picture.
    assert "day-03" in plain and "not-starred" not in plain
    assert "not-starred" in chosen
    assert "day-03" not in chosen
    assert rejected["day-03"] == "owner exclusion"


@pytest.mark.feature("trip.crosses-new-year")
def test_a_trip_over_new_year_is_one_trip_in_either_year():
    away = [
        picture("dec-30", datetime(2024, 12, 30, 11), where=FAR),
        picture("dec-31", datetime(2024, 12, 31, 22), where=FAR),
        picture("jan-01", datetime(2025, 1, 1, 10), where=FAR),
        picture("jan-02", datetime(2025, 1, 2, 16), where=FAR),
    ]

    (old_year,) = _trips_of(2024, away)
    (new_year,) = _trips_of(2025, away)

    for trip in (old_year, new_year):
        assert (trip.start_date.isoformat(), trip.end_date.isoformat()) == (
            "2024-12-30",
            "2025-01-02",
        )
        assert sorted(trip.asset_ids) == sorted(p.id for p in away)
