"""CLI album-mode helpers (#270)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.api.album_service import AlbumRef
from immich_memories.api.models import Asset, AssetType
from immich_memories.cli._album_generation import (
    CuratedPool,
    album_output_path,
    handle_album_generation,
)
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange


def test_output_filename_is_built_from_the_album_name():
    path = album_output_path(Path("/out/all_memories_2025.mp4"), "Trip 2025", "mp4")

    assert path == Path("/out/album_trip_2025.mp4")


def test_accented_album_names_survive_as_a_usable_filename():
    """Sam's albums are French — 'Récentes' must not become an empty slug."""
    path = album_output_path(Path("/out/x.mp4"), "Val d'Aoste 2021", "mkv")

    assert path == Path("/out/album_val_d_aoste_2021.mkv")


def test_a_name_with_no_usable_characters_still_yields_a_filename():
    path = album_output_path(Path("/out/x.mp4"), "***", "mp4")

    assert path == Path("/out/album.mp4")


class _Progress:
    """WHY: replaces the terminal progress display."""

    def add_task(self, *_args, **_kwargs):
        return 1

    def update(self, *_args, **_kwargs):
        return None

    def stop(self):
        return None


class _Client:
    """WHY: replaces the Immich API."""

    def __init__(self, album: AlbumRef, videos, images):
        self._album = album
        self._by_type = {AssetType.VIDEO: videos, AssetType.IMAGE: images}

    def resolve_album(self, _name_or_id):
        return self._album

    def get_assets_for_album(self, _album_id, *, asset_type, limit=None, progress_callback=None):
        return self._by_type[asset_type]


def _asset(asset_id: str, asset_type: AssetType, created: datetime) -> Asset:
    return Asset(
        id=asset_id,
        type=asset_type,
        fileCreatedAt=created,
        fileModifiedAt=created,
        updatedAt=created,
        width=1920,
        height=1080,
    )


def _run_album(monkeypatch, videos, images, **overrides):
    """Drive handle_album_generation, capturing what it hands the pipeline."""
    captured: dict = {}

    def _fake_pipeline(**kwargs):
        captured.update(kwargs)
        return Path("/out/album_trip_2025.mp4"), False, None

    # WHY: replaces the whole analysis + assembly pipeline.
    monkeypatch.setattr(
        "immich_memories.cli._pipeline_runner.run_pipeline_and_generate", _fake_pipeline
    )
    album = AlbumRef(id="a-1", name="Trip 2025", asset_count=len(videos) + len(images))
    kwargs = {
        "client": _Client(album, videos, images),
        "config": Config(),
        "progress": _Progress(),
        "album_ref": "Trip 2025",
        "person_names": [],
        "output_path": Path("/out/all_memories.mp4"),
        "use_live_photos": False,
        "use_photos": True,
        "transition": "fade",
        "music": None,
        "music_volume": 0.5,
        "no_music": True,
        "resolution": "4k",
        "scale_mode": None,
        "output_format": None,
        "add_date": False,
        "add_place": False,
        "keep_intermediates": False,
        "privacy_mode": False,
        "title_override": None,
        "subtitle_override": None,
        "upload_to_immich": False,
        "album": None,
    }
    kwargs.update(overrides)
    handle_album_generation(**kwargs)
    return captured


def test_the_album_supplies_the_pool_the_title_and_the_span(monkeypatch):
    videos = [_asset("v1", AssetType.VIDEO, datetime(2025, 7, 1, tzinfo=UTC))]
    images = [_asset("p1", AssetType.IMAGE, datetime(2025, 7, 9, tzinfo=UTC))]

    captured = _run_album(monkeypatch, videos, images)

    assert [a.id for a in captured["assets"]] == ["v1"]
    assert [a.id for a in captured["photo_assets"]] == ["p1"]
    assert captured["memory_type"] == "album"
    assert captured["title_override"] == "Trip 2025"
    assert captured["date_range"].start == datetime(2025, 7, 1, tzinfo=UTC)
    assert captured["date_range"].end == datetime(2025, 7, 9, tzinfo=UTC)
    assert captured["date_ranges"] == ()
    assert captured["memory_preset_params"] == {
        "album_name": "Trip 2025",
        "album_id": "a-1",
    }
    assert captured["output_path"] == Path("/out/album_trip_2025.mp4")


def test_an_explicit_title_still_wins_over_the_album_name(monkeypatch):
    videos = [_asset("v1", AssetType.VIDEO, datetime(2025, 7, 1, tzinfo=UTC))]

    captured = _run_album(monkeypatch, videos, [], title_override="Something Else")

    assert captured["title_override"] == "Something Else"


def test_album_no_render_reaches_shared_pipeline_without_reporting_a_video(monkeypatch, capsys):
    video = _asset("v1", AssetType.VIDEO, datetime(2025, 7, 1, tzinfo=UTC))
    captured = _run_album(monkeypatch, [video], [], no_render=True)
    assert captured["no_render"] is True
    assert captured["dry_run"] is False
    output = capsys.readouterr().out
    assert "Album selection complete; no video was created" in output
    assert "Album video:" not in output


def test_an_album_with_no_usable_media_stops_the_run(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run_album(monkeypatch, [], [])

    assert exc.value.code == 1


def test_a_written_subject_hands_the_album_over_as_a_subject_pool(monkeypatch):
    videos = [_asset("v1", AssetType.VIDEO, datetime(2025, 7, 1, tzinfo=UTC))]

    captured = _run_album(monkeypatch, videos, [], subject="Bread making along the years")

    assert captured["memory_preset_params"]["subject"] == "Bread making along the years"


def test_an_explicit_output_is_where_the_album_film_goes():
    asked = Path("/films/holiday.mp4")

    assert album_output_path(asked, "Trip 2025", "mp4", explicit=True) == asked


class _AssetsById(_Client):
    """WHY: replaces the Immich API; a curated pool is read from its window, never as an album."""

    def __init__(self, assets):
        super().__init__(AlbumRef(id="unused", name="unused", asset_count=0), [], [])
        self._by_id = {asset.id: asset for asset in assets}

    def resolve_album(self, _name_or_id):
        raise AssertionError("a curated pool is no Immich album")

    def search_metadata(self, **query):
        return _PagedImmich(list(self._by_id.values())).search_metadata(**query)


def test_a_curated_pool_is_read_from_immich_and_filmed_as_an_album_of_its_subject(monkeypatch):
    video = _asset("v1", AssetType.VIDEO, datetime(2024, 3, 1, tzinfo=UTC))
    photo = _asset("p1", AssetType.IMAGE, datetime(2025, 7, 9, tzinfo=UTC))
    pool = CuratedPool(
        name="our cat along the years",
        ref="ask-1234",
        asset_ids=("v1", "p1"),
        window=DateRange(start=video.file_created_at, end=photo.file_created_at),
    )

    captured = _run_album(
        monkeypatch,
        [],
        [],
        client=_AssetsById([video, photo]),
        album_ref=pool.ref,
        curated=pool,
        subject=pool.name,
    )

    assert [a.id for a in captured["assets"]] == ["v1"]
    assert [a.id for a in captured["photo_assets"]] == ["p1"]
    assert captured["memory_preset_params"] == {
        "album_name": "our cat along the years",
        "album_id": "ask-1234",
        "subject": "our cat along the years",
    }


class _PagedImmich:
    """WHY: replaces the Immich API; it pages a date range's assets and counts every call."""

    def __init__(self, assets):
        self.assets = sorted(assets, key=lambda a: a.file_created_at)
        self.calls = 0

    def get_asset(self, asset_id):
        self.calls += 1
        return next(asset for asset in self.assets if asset.id == asset_id)

    def search_metadata(self, *, page, size, taken_after, taken_before, **_filters):
        from immich_memories.api.models import MetadataSearchResult

        self.calls += 1
        inside = [a for a in self.assets if taken_after <= a.file_created_at <= taken_before]
        items = inside[(page - 1) * size : page * size]
        more = page * size < len(inside)
        return MetadataSearchResult.model_validate(
            {
                "assets": {
                    "items": items,
                    "total": len(items),
                    "nextPage": str(page + 1) if more else None,
                }
            }
        )


def test_a_large_pool_is_read_in_pages_not_one_call_per_picture():
    from datetime import timedelta

    from immich_memories.cli._album_generation import pool_media

    first = datetime(2020, 1, 1, tzinfo=UTC)
    library = [_asset(f"p{n}", AssetType.IMAGE, first + timedelta(hours=n)) for n in range(3000)]
    pool = [asset.id for asset in library[:2500]]
    immich = _PagedImmich(library)
    window = DateRange(start=first, end=first + timedelta(hours=2499))

    media = pool_media(
        immich, pool, Config(), window=window, use_live_photos=False, use_photos=True
    )

    assert sorted(a.id for a in media.photos) == sorted(pool)
    # 2,500 pictures (and the 500 around them) in pages of 1,000, not 2,500 single reads.
    assert immich.calls <= 4
