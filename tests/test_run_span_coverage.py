"""A run's spans account for its wall time, whichever route found the pictures (#1429)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from immich_memories.analysis.trip_detection import DetectedTrip
from immich_memories.api.models import Asset
from immich_memories.cli._live_display import QuietDisplay
from immich_memories.config_loader import Config
from immich_memories.tracking import timing
from immich_memories.tracking.span_progress import uncovered_seconds


class _Clock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def spend(self, seconds: float) -> None:
        self.seconds += seconds


def _video(asset_id: str) -> Asset:
    moment = datetime(2031, 4, 9, 12, tzinfo=UTC)
    return Asset(
        id=asset_id,
        type="VIDEO",
        fileCreatedAt=moment,
        fileModifiedAt=moment,
        updatedAt=moment,
    )


class _SlowLibrary:
    """Reads that take library time on the run's clock."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock

    def get_videos_for_date_range(self, date_range):
        self.clock.spend(2.0)
        return [_video("video-1")]

    def get_photos_for_date_range(self, date_range):
        self.clock.spend(1.0)
        return []


def _pipeline_taking(clock: _Clock, seconds: float):
    def run_pipeline_and_generate(**kwargs):
        with timing.span("pipeline"):
            clock.spend(seconds)
        return kwargs["output_path"], False, None

    return run_pipeline_and_generate


def _run_trip(monkeypatch, tmp_path: Path, clock: _Clock) -> timing.Collector:
    from immich_memories.cli._trip_generation import handle_trip_generation

    trip = DetectedTrip(
        start_date=date(2031, 4, 8),
        end_date=date(2031, 4, 12),
        location_name="Test destination",
        asset_count=3,
        centroid_lat=45.0,
        centroid_lon=8.0,
    )

    def slow_detection(*args, **kwargs):
        clock.spend(30.0)
        return [trip]

    # WHY: detection reads a year of Immich assets; this stands in for those 30 s of reads.
    monkeypatch.setattr("immich_memories.cli._trip_display.discover_year_trips", slow_detection)
    # WHY: the cut and render are measured by their own span; this is that span, 60 s long.
    monkeypatch.setattr(
        "immich_memories.cli._trip_generation.run_pipeline_and_generate",
        _pipeline_taking(clock, 60.0),
    )
    config = Config()
    with timing.collecting(now=clock) as collected, timing.span("run"):
        handle_trip_generation(
            client=_SlowLibrary(clock),  # type: ignore[arg-type]
            config=config,
            progress=QuietDisplay(),
            year=2031,
            month=None,
            trip_index=None,
            all_trips=True,
            near_date=None,
            person_names=[],
            output_path=tmp_path / "trip.mp4",
            use_live_photos=False,
            use_photos=True,
            transition="cut",
            music=None,
            music_volume=0.5,
            no_music=True,
            resolution="1080p",
            scale_mode=None,
            output_format=None,
            add_date=False,
            add_place=False,
            keep_intermediates=False,
            privacy_mode=False,
            title_override=None,
            subtitle_override=None,
            upload_to_immich=False,
            album=None,
            no_render=True,
        )
    return collected


def test_a_trip_runs_discovery_is_measured_before_its_pipeline(monkeypatch, tmp_path):
    clock = _Clock()
    collected = _run_trip(monkeypatch, tmp_path, clock)

    discovery = [span for span in collected.spans if span.name == "discovery"]
    assert sum(span.duration for span in discovery) == pytest.approx(33.0)
    assert uncovered_seconds(collected.spans, clock.seconds) == pytest.approx(0.0)


class _SlowAlbum:
    """An album whose resolution and reads take library time on the run's clock."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock

    def resolve_album(self, name_or_id):
        from immich_memories.api.album_service import AlbumRef

        self.clock.spend(1.0)
        return AlbumRef(id="album-1", name="Test album", asset_count=1)

    def get_assets_for_album(self, album_id, *, asset_type, limit=None, progress_callback=None):
        from immich_memories.api.models import AssetType

        self.clock.spend(20.0)
        return [_video("video-1")] if asset_type == AssetType.VIDEO else []


def test_an_album_runs_discovery_is_measured_before_its_pipeline(monkeypatch, tmp_path):
    from immich_memories.cli._album_generation import handle_album_generation

    clock = _Clock()
    # WHY: the cut and render are measured by their own span; this is that span, 60 s long.
    monkeypatch.setattr(
        "immich_memories.cli._pipeline_runner.run_pipeline_and_generate",
        _pipeline_taking(clock, 60.0),
    )
    with timing.collecting(now=clock) as collected, timing.span("run"):
        handle_album_generation(
            client=_SlowAlbum(clock),  # type: ignore[arg-type]
            config=Config(),
            progress=QuietDisplay(),
            album_ref="Test album",
            person_names=[],
            output_path=tmp_path / "album.mp4",
            use_live_photos=False,
            use_photos=True,
            transition="cut",
            music=None,
            music_volume=0.5,
            no_music=True,
            resolution="1080p",
            scale_mode=None,
            output_format=None,
            add_date=False,
            add_place=False,
            keep_intermediates=False,
            privacy_mode=False,
            title_override=None,
            subtitle_override=None,
            upload_to_immich=False,
            album=None,
            no_render=True,
        )

    discovery = [span for span in collected.spans if span.name == "discovery"]
    assert sum(span.duration for span in discovery) == pytest.approx(41.0)
    assert uncovered_seconds(collected.spans, clock.seconds) == pytest.approx(0.0)
