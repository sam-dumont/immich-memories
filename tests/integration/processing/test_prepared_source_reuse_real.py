"""A second render of the same selection prepares no source again (#2032).

Real FFmpeg throughout: the videos are stream-cut, the photos rendered through the
Ken Burns encoder. Only the Immich download is a stand-in that copies local bytes.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from immich_memories.api.models import AssetType
from immich_memories.cache.prepared_source_bank import PreparedSourceBank
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import extract_clips
from immich_memories.generate_downloads import fetch_temporary_asset
from immich_memories.processing.download_coordinator import DownloadCoordinator
from immich_memories.processing.output_canvas import OutputCanvas
from immich_memories.processing.probe_cache import ProbeCache
from tests.conftest import make_clip

pytestmark = pytest.mark.integration

VIDEOS = ("video-a", "video-b", "video-c")
PHOTOS = ("photo-a", "photo-b", "photo-c")
# One instant for every listing: Immich reports the same asset the same way twice.
TAKEN = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def _video(path: Path, seconds: int, hue: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={300 + hue}:duration={seconds}",
            "-vf",
            f"hue=h={hue}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "15",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        timeout=60,
    )


@pytest.fixture(scope="module")
def originals(tmp_path_factory) -> dict[str, Path]:
    """What Immich would serve: three 1080p videos and three 12 MP photos."""
    root = tmp_path_factory.mktemp("originals")
    served = {}
    for index, asset_id in enumerate(VIDEOS):
        served[asset_id] = root / f"{asset_id}.mp4"
        _video(served[asset_id], seconds=6, hue=index * 90)
    for index, asset_id in enumerate(PHOTOS):
        served[asset_id] = root / f"{asset_id}.jpg"
        Image.new("RGB", (4000, 3000), (60 + 50 * index, 140, 90)).save(served[asset_id])
    return served


class _Immich:
    """Serves local bytes and counts every original it hands out."""

    downloads: list[str] = []
    _lock = threading.Lock()
    served: dict[str, Path] = {}

    def download_asset(self, asset_id, destination, expected_size_bytes=None, edited=False):
        with self._lock:
            self.downloads.append(asset_id)
        shutil.copyfile(self.served[asset_id], destination)

    def get_asset_faces(self, _asset_id):
        # No face recognised: each still moves toward its centre.
        return []

    def close(self):
        pass


def _clips():
    clips = []
    for asset_id in VIDEOS:
        clip = make_clip(asset_id, width=1920, height=1080, duration=6, file_created_at=TAKEN)
        clip.asset.original_file_name = f"{asset_id}.mp4"
        clip.asset.checksum = f"checksum-{asset_id}"
        clips.append(clip)
    for asset_id in PHOTOS:
        clip = make_clip(asset_id, width=4000, height=3000, duration=3, file_created_at=TAKEN)
        clip.asset.type = AssetType.IMAGE
        clip.asset.original_file_name = f"{asset_id}.jpg"
        clip.asset.checksum = f"checksum-{asset_id}"
        clips.append(clip)
    return clips


def _render(run_dir: Path, bank_dir: Path, clips=None) -> tuple[list, PreparedSourceBank, float]:
    config = Config()
    config.hardware.enabled = False
    config.photos.duration = 3
    params = GenerationParams(
        clips=clips or _clips(),
        output_path=run_dir / "film.mp4",
        config=config,
        output_canvas=OutputCanvas(1920, 1080, "landscape"),
        clip_segments=dict.fromkeys(VIDEOS, (1.0, 4.0)),
    )
    bank = PreparedSourceBank(bank_dir, max_bytes=10**10)
    bank.begin_run()
    coordinator = DownloadCoordinator(
        _Immich,
        None,
        max_workers=2,
        download_operation=lambda client, asset: fetch_temporary_asset(client, asset, run_dir),
    )
    started = time.perf_counter()
    clips = extract_clips(
        params, None, run_dir, download_coordinator=coordinator, prepared_sources=bank
    )
    return clips, bank, time.perf_counter() - started


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_second_render_of_the_same_clips_prepares_nothing(tmp_path, originals):
    _Immich.served = originals
    _Immich.downloads = []
    bank_dir = tmp_path / "cache" / "prepared-sources"

    first, first_bank, first_seconds = _render(tmp_path / "run1", bank_dir)
    first_downloads = len(_Immich.downloads)
    _Immich.downloads = []
    second, second_bank, second_seconds = _render(tmp_path / "run2", bank_dir)

    print(
        f"\nfirst render: {first_seconds:.2f} s, {first_downloads} downloads, "
        f"{first_bank.kept} prepared and banked"
        f"\nsecond render: {second_seconds:.2f} s, {len(_Immich.downloads)} downloads, "
        f"{second_bank.taken} reused, {second_bank.kept} prepared"
    )
    assert first_downloads == len(VIDEOS) + len(PHOTOS)
    assert first_bank.kept == len(first) == 6
    assert _Immich.downloads == []
    assert (second_bank.taken, second_bank.kept) == (6, 0)
    assert second_seconds < first_seconds
    # The same film, source for source: order, kind, timing and bytes.
    assert [clip.asset_id for clip in second] == [clip.asset_id for clip in first]
    assert [(c.is_photo, c.duration) for c in second] == [(c.is_photo, c.duration) for c in first]
    assert [_sha(clip.path) for clip in second] == [_sha(clip.path) for clip in first]
    # Each run reads its own files: photos inside its own run folder.
    for clip in second:
        if clip.is_photo:
            assert clip.path.is_relative_to(tmp_path / "run2")
        assert ProbeCache().get(clip.path).has_video


def test_a_replaced_original_is_prepared_again(tmp_path, originals):
    _Immich.served = originals
    bank_dir = tmp_path / "cache" / "prepared-sources"
    _render(tmp_path / "run1", bank_dir)

    _Immich.downloads = []
    clips = _clips()
    clips[1].asset.checksum = "the-owner-replaced-this-file"
    _prepared, bank, _seconds = _render(tmp_path / "run2", bank_dir, clips)

    assert _Immich.downloads == ["video-b"]
    assert (bank.taken, bank.kept) == (5, 1)
