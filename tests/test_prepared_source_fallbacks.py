"""A preparation that fell back is never banked, so the next run tries again (#2032).

Each case drives the real code where a fallback is decided, with one failure
injected, and checks the result stays out of the bank while a clean preparation of
the same source in the next run is prepared and then banked.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from immich_memories import generate_clips, generate_downloads
from immich_memories.api.models import AssetType
from immich_memories.cache.prepared_source_bank import PreparedSourceBank
from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import extract_clips
from immich_memories.generate_downloads import _try_merge_burst, download_clip
from immich_memories.generate_prepared_sources import PreparationRequest, reuse_or_prepare
from immich_memories.photos import animator
from immich_memories.processing import clips as clip_module
from immich_memories.processing import live_photo_merger
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.clips import extract_clip
from immich_memories.processing.download_coordinator import DownloadResult
from immich_memories.processing.hardware import HWAccelCapabilities
from immich_memories.processing.live_photo_merger import burst_fps
from immich_memories.processing.output_canvas import OutputCanvas
from immich_memories.processing.preparation_fallbacks import note_fallback, watching_fallbacks
from tests.conftest import make_clip

TAKEN = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
# Three 1.5 s components: losing one still leaves 3.0 s, over the 2.5 s motion floor (#2453).
BURST = ["burst-1", "burst-2", "burst-3"]
TRIMS = [(0.0, 1.5)] * len(BURST)


def _ffmpeg_video(path: Path, *, audio: bool) -> Path:
    sound = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1.6"] if audio else []
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=1.6",
            *sound,
            "-c:v", "libx264", "-preset", "ultrafast",
            *(["-c:a", "aac", "-shortest"] if audio else ["-an"]),
            str(path),
        ],
        check=True,
        timeout=30,
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("media")
    junk = root / "junk.MOV"
    junk.write_bytes(b"not a video at all" * 100)
    return {
        "silent": _ffmpeg_video(root / "silent.mp4", audio=False),
        "silent-2": _ffmpeg_video(root / "silent-2.mp4", audio=False),
        "voiced-1": _ffmpeg_video(root / "voiced-1.mp4", audio=True),
        "voiced-2": _ffmpeg_video(root / "voiced-2.mp4", audio=True),
        "junk": junk,
    }


class _Immich:
    """Serves a few bytes per asset; ids listed in ``failing`` raise like a dropped request."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        self.failing = failing

    def download_asset(self, asset_id, destination, expected_size_bytes=None):
        if asset_id in self.failing:
            raise OSError("connection reset")
        Path(destination).write_bytes(b"companion bytes")


def _live_clip():
    clip = make_clip("live-1", file_created_at=TAKEN)
    clip.asset.type = AssetType.IMAGE
    clip.asset.live_photo_video_id = "companion-1"
    clip.asset.checksum = "sha1-of-the-still"
    clip.live_burst_video_ids = list(BURST)
    clip.live_burst_trim_points = list(TRIMS)
    return clip


def _merged_by_stand_in(monkeypatch) -> None:
    def merge(paths, trims, merged_path, **_kwargs):
        merged_path.write_bytes(b"merged")
        return merged_path

    # WHY: the FFmpeg merge is the boundary; these cases are about which components reach it.
    monkeypatch.setattr(generate_downloads, "_try_merge_burst", merge)


def _held_still(out: Path) -> Path:
    """The picture's still, which the run renders when its burst cannot play."""
    still = out / "still.mp4"
    still.write_bytes(b"the still, animated")
    return still


def _still_with_no_components(out: Path, media, monkeypatch) -> Path | None:
    failed = {key: DownloadResult(key, key, None, "timed out") for key in BURST}
    assert (
        download_clip(_Immich(), None, _live_clip(), out, prefetched_burst_results=failed) is None
    )
    return _held_still(out)


def _still_with_no_readable_component(out: Path, media, monkeypatch) -> Path | None:
    unreadable = {key: DownloadResult(key, key, media["junk"]) for key in BURST}
    burst = download_clip(_Immich(), None, _live_clip(), out, prefetched_burst_results=unreadable)
    assert burst is None
    return _held_still(out)


def _partial_prefetched_burst(out: Path, media, monkeypatch) -> Path | None:
    _merged_by_stand_in(monkeypatch)
    results = {
        BURST[0]: DownloadResult(BURST[0], BURST[0], None, "timed out"),
        **{key: DownloadResult(key, key, media["silent"]) for key in BURST[1:]},
    }
    return download_clip(_Immich(), None, _live_clip(), out, prefetched_burst_results=results)


def _partial_downloaded_burst(out: Path, media, monkeypatch) -> Path | None:
    _merged_by_stand_in(monkeypatch)
    return download_clip(_Immich(failing=(BURST[0],)), None, _live_clip(), out)


def _merge_without_unreadable_component(out: Path, media, monkeypatch) -> Path | None:
    return _try_merge_burst(
        [media["silent"], media["silent-2"], media["junk"]],
        list(TRIMS),
        out / "merged.mp4",
        hardware_enabled=False,
    )


def _timestamp_trims_after_failed_alignment(out: Path, media, monkeypatch) -> Path | None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("alignment found no peak")

    # WHY: forces the spectrogram aligner to fail; the merge itself is real FFmpeg.
    monkeypatch.setattr(live_photo_merger, "align_clips_spectrogram", fail)
    return _try_merge_burst(
        [media["voiced-1"], media["voiced-2"]],
        list(TRIMS[:2]),
        out / "merged.mp4",
        shutter_timestamps=[0.0, 0.6],
        hardware_enabled=False,
    )


def _cadence_without_unreadable_source(out: Path, media, monkeypatch) -> Path | None:
    assert burst_fps([media["junk"]]) > 0
    stand_in = out / "merged.mp4"
    stand_in.write_bytes(b"merged at a guessed cadence")
    return stand_in


def _software_after_hardware_failure(out: Path, media, monkeypatch) -> Path | None:
    config = Config()
    config.hardware.enabled = True
    # WHY: a hardware encoder that fails on this machine, whatever the machine has.
    monkeypatch.setattr(
        clip_module, "_get_hw_caps", lambda: HWAccelCapabilities(supports_h264_encode=True)
    )
    monkeypatch.setattr(clip_module, "get_ffmpeg_encoder", lambda *_a, **_k: ("h264_absent", []))
    return extract_clip(
        media["silent"], 0.0, 0.5, output_path=out / "cut.mp4", reencode=True, config=config
    )


_GAIN_KEY = "urn:com:apple:photo:2020:aux:hdrgainmap"


def _gain_mapped_heic(out: Path, monkeypatch, gain: Callable[[], Image.Image]) -> Path:
    pi_heif = pytest.importorskip("pi_heif")
    # WHY: pi-heif only decodes; the dev-only pillow-heif writes the test picture.
    pillow_heif = pytest.importorskip("pillow_heif")
    exif = Image.Exif()
    header = b"Apple iOS\x00\x00\x01MM" + struct.pack(">H", 2)
    entries = struct.pack(">HHII", 0x0021, 10, 1, 40) + struct.pack(">HHII", 0x0030, 10, 1, 48)
    exif.get_ifd(0x8769)[0x927C] = header + entries + struct.pack(">iiii", 101, 100, 608, 100000)
    path = out / "IMG_0001.HEIC"
    pixels = np.full((32, 48, 3), 120, dtype=np.uint8)
    pillow_heif.from_pillow(Image.fromarray(pixels)).save(path, quality=90, exif=exif.tobytes())

    class Aux:
        def to_pillow(self):
            return gain()

    class Primary:
        info = {"aux": {_GAIN_KEY: [7]}}

        def get_aux_image(self, _item):
            return Aux()

    # WHY: pillow-heif cannot write an auxiliary gain-map image, so reading one is
    # the stand-in; the primary picture and its EXIF are a real HEIC.
    monkeypatch.setattr(pi_heif, "open_heif", lambda *_args, **_kwargs: [Primary()])
    return path


def _sdr_after_unreadable_gain_map(out: Path, media, monkeypatch) -> Path | None:
    def unreadable() -> Image.Image:
        raise ValueError("corrupt auxiliary image")

    source = _gain_mapped_heic(out, monkeypatch, unreadable)
    return animator.prepare_photo_source(source, out).path


def _sdr_without_opencv(out: Path, media, monkeypatch) -> Path | None:
    source = _gain_mapped_heic(out, monkeypatch, lambda: Image.new("L", (12, 8), 128))
    monkeypatch.setitem(sys.modules, "cv2", None)  # an install without OpenCV
    return animator.prepare_photo_source(source, out).path


FALLBACKS = {
    "still, no burst component downloaded": _still_with_no_components,
    "still, no burst component readable": _still_with_no_readable_component,
    "burst merged without a component whose prefetch failed": _partial_prefetched_burst,
    "burst merged without a component whose download failed": _partial_downloaded_burst,
    "burst merged without a component ffprobe cannot read": _merge_without_unreadable_component,
    "timestamp trims after spectrogram alignment failed": _timestamp_trims_after_failed_alignment,
    "burst cadence guessed without an unreadable source": _cadence_without_unreadable_source,
    "software encode after the hardware encoder failed": _software_after_hardware_failure,
    "SDR photo after its gain map could not be read": _sdr_after_unreadable_gain_map,
    "SDR photo without OpenCV": _sdr_without_opencv,
}


def _request(output_dir: Path) -> PreparationRequest:
    clip = _live_clip()
    config = Config()
    config.hardware.enabled = False
    params = GenerationParams(
        clips=[clip],
        output_path=output_dir / "film.mp4",
        config=config,
        output_canvas=OutputCanvas(1920, 1080, "landscape"),
    )
    return PreparationRequest(params, clip, None, output_dir)


def _bankable(produced: Path | None, output_dir: Path) -> AssemblyClip:
    """What the run would hand to assembly, at a place the bank accepts."""
    assert produced is not None and produced.is_file()
    path = output_dir / "photos" / "live-1_photo.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, path)
    return AssemblyClip(path=path, duration=1.0, asset_id="live-1", is_photo=True)


def _dress(path: Path, duration: float) -> AssemblyClip:
    return AssemblyClip(path=path, duration=duration, asset_id="live-1")


@pytest.mark.parametrize("fallback", list(FALLBACKS.values()), ids=list(FALLBACKS))
def test_a_fallback_result_is_not_banked_and_the_next_run_retries(
    fallback, tmp_path, media, monkeypatch
):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    run1 = tmp_path / "run1"
    run1.mkdir()

    first = reuse_or_prepare(
        bank,
        _request(run1),
        prepare=lambda: _bankable(fallback(run1, media, monkeypatch), run1),
        dress=_dress,
    )
    monkeypatch.undo()  # the transient failure has passed

    assert first is not None  # this film still gets the fallback
    assert bank.kept == 0
    run2 = tmp_path / "run2"
    retried: list[Path] = []

    def clean() -> AssemblyClip:
        retried.append(run2)
        produced = run2 / "merged.mp4"
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_bytes(b"the intended preparation")
        return _bankable(produced, run2)

    reuse_or_prepare(bank, _request(run2), prepare=clean, dress=_dress)

    assert retried == [run2]
    assert bank.kept == 1


def test_a_fallback_noted_outside_a_watch_goes_nowhere():
    note_fallback("no preparation is being watched")
    with watching_fallbacks() as noted:
        pass
    assert noted == []


def test_an_unmeasured_segment_is_not_banked_and_the_next_run_measures_it(
    tmp_path, media, monkeypatch
):
    clip = make_clip("video-1", width=64, height=64, duration=0.6, file_created_at=TAKEN)
    clip.asset.checksum = "sha1-of-the-original"
    clip.local_path = str(media["silent"])
    config = Config()
    config.hardware.enabled = False

    def render(run: Path) -> tuple[list[AssemblyClip], PreparedSourceBank]:
        bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
        params = GenerationParams(
            clips=[clip],
            output_path=run / "film.mp4",
            config=config,
            output_canvas=OutputCanvas(64, 64, "landscape"),
            clip_segments={"video-1": (0.0, 0.5)},
        )
        return extract_clips(params, None, run, prepared_sources=bank), bank

    # WHY: ffprobe failing to measure the cut, so its requested length stands in.
    monkeypatch.setattr(generate_clips, "probe_file_duration", lambda *_a, **_k: None)
    first, first_bank = render(tmp_path / "run1")
    monkeypatch.undo()
    second, second_bank = render(tmp_path / "run2")

    assert len(first) == 1 and first_bank.kept == 0
    assert (second_bank.taken, second_bank.kept) == (0, 1)
    assert second[0].duration <= 0.5
