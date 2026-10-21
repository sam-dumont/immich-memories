"""The instant a finished memory is filed under, and how it is written down."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from immich_memories.api.models import Asset, AssetType, ExifInfo
from immich_memories.delivery_timestamp import (
    capture_metadata_args,
    carry_capture_instant,
    film_capture_instant,
    stamp_capture_instant,
)

PARIS_SUMMER = timezone(timedelta(hours=2))
PARIS_WINTER = timezone(timedelta(hours=1))


def _picture(local: datetime, *, original: datetime | None = None) -> Asset:
    """An asset shot at the given local wall clock, the way Immich reports one.

    Immich sends ``localDateTime`` as the local wall clock with a Z suffix, and
    ``fileCreatedAt`` as the same instant in real UTC.
    """
    instant = local.astimezone(UTC)
    wall_clock = local.replace(tzinfo=UTC)
    return Asset(
        id="picture-" + local.isoformat().replace(":", "-").replace("+", ""),
        type=AssetType.IMAGE,
        fileCreatedAt=instant,
        fileModifiedAt=instant,
        updatedAt=instant,
        localDateTime=wall_clock,
        exifInfo=ExifInfo(dateTimeOriginal=original) if original else None,
    )


class TestFilmCaptureInstant:
    def test_last_picture_in_the_zone_most_pictures_share(self):
        """Three pictures at +02:00 and one at +01:00: the last, in +02:00."""
        pictures = [
            _picture(datetime(2024, 6, 19, 9, 0, tzinfo=PARIS_SUMMER)),
            _picture(datetime(2024, 6, 19, 12, 30, tzinfo=PARIS_SUMMER)),
            _picture(datetime(2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER)),
            _picture(datetime(2024, 6, 18, 8, 0, tzinfo=PARIS_WINTER)),
        ]

        assert film_capture_instant(pictures) == datetime(2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER)

    def test_last_picture_from_another_zone_is_told_in_the_shared_one(self):
        """The last picture is at +01:00, most are at +02:00: same instant, +02:00 clock."""
        pictures = [
            _picture(datetime(2024, 6, 19, 9, 0, tzinfo=PARIS_SUMMER)),
            _picture(datetime(2024, 6, 19, 12, 30, tzinfo=PARIS_SUMMER)),
            _picture(datetime(2024, 6, 20, 17, 45, tzinfo=PARIS_WINTER)),
        ]

        result = film_capture_instant(pictures)

        assert result == datetime(2024, 6, 20, 17, 45, tzinfo=PARIS_WINTER)
        assert result.utcoffset() == timedelta(hours=2)
        assert result.isoformat() == "2024-06-20T18:45:00+02:00"

    def test_exif_offset_is_read_when_the_local_clock_is_missing(self):
        """A picture without localDateTime still has a zone if EXIF carries one."""
        instant = datetime(2024, 6, 20, 16, 45, tzinfo=UTC)
        picture = Asset(
            id="picture-exif",
            type=AssetType.IMAGE,
            fileCreatedAt=instant,
            fileModifiedAt=instant,
            updatedAt=instant,
            exifInfo=ExifInfo(dateTimeOriginal=instant.astimezone(PARIS_SUMMER)),
        )

        assert film_capture_instant([picture]).utcoffset() == timedelta(hours=2)

    def test_no_usable_time_files_nothing(self):
        instant = datetime(2024, 6, 20, 16, 45, tzinfo=UTC)
        picture = Asset(
            id="picture-bare",
            type=AssetType.IMAGE,
            fileCreatedAt=instant,
            fileModifiedAt=instant,
            updatedAt=instant,
        )

        assert film_capture_instant([picture]) is None
        assert film_capture_instant([]) is None


class TestCaptureMetadataArgs:
    def test_only_the_local_capture_tag_is_a_metadata_key(self):
        # creation_time as a key would land in the Keys list beside the movie
        # header, and FFmpeg 7+ reads the pair back as "a;b".
        args = capture_metadata_args(datetime(2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER))

        assert args == [
            "-metadata",
            "com.apple.quicktime.creationdate=2024-06-20T18:45:00+02:00",
        ]

    def test_no_instant_adds_no_arguments(self):
        assert capture_metadata_args(None) == []


class TestDeliveryFilesTheMemoryOnItsOwnDay:
    def test_upload_carries_the_last_picture_s_instant(self, tmp_path):
        from unittest.mock import MagicMock

        from immich_memories.api.models import VideoClipInfo
        from immich_memories.generate import GenerationParams
        from immich_memories.generate_delivery import deliver_completed_artifact

        film = tmp_path / "memory.mp4"
        film.write_bytes(b"film")
        clips = [
            VideoClipInfo(asset=_picture(datetime(2024, 6, 19, 9, 0, tzinfo=PARIS_SUMMER))),
            VideoClipInfo(asset=_picture(datetime(2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER))),
        ]
        # WHY: uploading is a write against a live Immich server.
        client = MagicMock()
        client.upload_memory.return_value = {"asset_id": "asset-1"}
        params = GenerationParams(
            clips=clips,
            output_path=film,
            config=MagicMock(),
            client=client,
            upload_enabled=True,
        )

        deliver_completed_artifact(params, film, MagicMock())

        assert client.upload_memory.call_args.kwargs["captured_at"] == datetime(
            2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER
        )


requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _film(path: Path, *extra: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=0.2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", *extra, str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def _creation_times(path: Path) -> list[str]:
    """creation_time as ffprobe reads it from the container and from every stream."""
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
        )
    )
    tagged = [probe["format"], *probe["streams"]]
    return [entry.get("tags", {}).get("creation_time", "") for entry in tagged]


@requires_ffmpeg
class TestMovieHeaderInstant:
    def test_stamping_dates_the_movie_and_every_track_once(self, tmp_path):
        film = _film(tmp_path / "film.mp4", "-movflags", "+faststart")

        stamp_capture_instant(film, datetime(2024, 6, 20, 18, 45, tzinfo=PARIS_SUMMER))

        assert _creation_times(film) == ["2024-06-20T16:45:00.000000Z"] * 2

    def test_no_instant_leaves_the_film_undated(self, tmp_path):
        film = _film(tmp_path / "film.mp4")

        stamp_capture_instant(film, None)
        stamp_capture_instant(tmp_path / "never-rendered.mp4", datetime(2024, 6, 20, tzinfo=UTC))

        assert _creation_times(film) == ["", ""]
        assert not (tmp_path / "never-rendered.mp4").exists()

    def test_a_rebuilt_film_keeps_its_source_instant(self, tmp_path):
        source = _film(tmp_path / "source.mp4")
        stamp_capture_instant(source, datetime(2024, 6, 20, 16, 45, tzinfo=UTC))
        rebuilt = _film(tmp_path / "rebuilt.mp4")

        carry_capture_instant(source, rebuilt)

        assert _creation_times(rebuilt) == ["2024-06-20T16:45:00.000000Z"] * 2

    def test_an_undated_source_carries_nothing(self, tmp_path):
        rebuilt = _film(tmp_path / "rebuilt.mp4")

        carry_capture_instant(_film(tmp_path / "source.mp4"), rebuilt)
        carry_capture_instant(tmp_path / "never-rendered.mp4", rebuilt)

        assert _creation_times(rebuilt) == ["", ""]

    def test_a_64_bit_movie_header_is_read_and_written(self, tmp_path):
        # Version 1 headers carry 64-bit times; build one by hand, as FFmpeg
        # only writes them past 2040.
        mvhd_v1 = struct.pack(">I4sB3xQQIQ", 40, b"mvhd", 1, 0, 0, 1000, 0)
        moov = struct.pack(">I4s", 8 + len(mvhd_v1), b"moov") + mvhd_v1
        source = tmp_path / "v1.mp4"
        source.write_bytes(struct.pack(">I4s", 1, b"free") + struct.pack(">Q", 16) + moov)
        stamp_capture_instant(source, datetime(2024, 6, 20, 16, 45, tzinfo=UTC))
        rebuilt = _film(tmp_path / "rebuilt.mp4")

        carry_capture_instant(source, rebuilt)

        assert _creation_times(rebuilt) == ["2024-06-20T16:45:00.000000Z"] * 2
