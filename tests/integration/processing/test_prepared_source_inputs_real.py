"""Change one preparation input, render again, and the film gets what that input asks for (#2452).

Each case renders a source into a prepared-source bank, changes one thing the
preparation reads, and renders again. The second render must prepare the source
afresh, and what it hands to assembly must match a render of the changed source
that never saw the bank. Real FFmpeg throughout; Immich is a stand-in serving
local bytes.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import AssetType, VideoClipInfo
from immich_memories.cache.prepared_source_bank import PreparedSourceBank
from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import extract_clips
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import HdrMode
from immich_memories.processing.output_canvas import OutputCanvas
from immich_memories.processing.probe_cache import ProbeCache
from tests.conftest import make_clip

pytestmark = pytest.mark.integration

TAKEN = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
ORIGINAL_RGB = (200, 40, 40)
EDITED_RGB = (40, 40, 200)


def _video(path: Path, seconds: float, hue: int) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency={300 + hue}:duration={seconds}",
            "-vf", f"hue=h={hue}", "-c:v", "libx264", "-preset", "ultrafast", "-g", "15",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
        timeout=60,
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> dict[str, Path]:
    """What Immich would serve for each asset id, and for an edited photo its edit."""
    root = tmp_path_factory.mktemp("served")
    files = {
        "video-1": _video(root / "video-1.mp4", 4, 0),
        "burst-1": _video(root / "burst-1.mov", 2, 60),
        "burst-2": _video(root / "burst-2.mov", 2, 120),
        "companion-1": _video(root / "companion-1.mov", 2, 180),
    }
    for name, rgb in (
        ("photo-1", ORIGINAL_RGB),
        ("photo-1:edited", EDITED_RGB),
        ("live-1", ORIGINAL_RGB),
    ):
        files[name] = root / f"{name.replace(':', '-')}.jpg"
        Image.new("RGB", (1200, 900), rgb).save(files[name])
    return files


class _Immich:
    """Copies the served bytes; asks for the edit when the run asks for it."""

    def __init__(self, served: dict[str, Path]) -> None:
        self.served = served

    def get_asset_faces(self, _asset_id):
        # No face recognised: each still moves toward its centre.
        return []

    def download_asset(self, asset_id, destination, expected_size_bytes=None, edited=False):
        shutil.copyfile(self.served[f"{asset_id}:edited" if edited else asset_id], destination)


@dataclass
class _Source:
    """One selected source and everything about the run that prepares it."""

    clip: VideoClipInfo
    directive: EditorialSelection | None = None
    segment: tuple[float, float] | None = None
    canvas: OutputCanvas = field(default_factory=lambda: OutputCanvas(640, 360, "landscape"))
    photo_seconds: float = 2.0
    hdr: bool = False


def _photo() -> _Source:
    clip = make_clip("photo-1", width=1200, height=900, duration=2, file_created_at=TAKEN)
    clip.asset.type = AssetType.IMAGE
    clip.asset.original_file_name = "photo-1.jpg"
    clip.asset.checksum = "sha1-photo-1"
    return _Source(clip)


def _video_source() -> _Source:
    clip = make_clip("video-1", width=640, height=360, duration=4, file_created_at=TAKEN)
    clip.asset.original_file_name = "video-1.mp4"
    clip.asset.checksum = "sha1-video-1"
    return _Source(clip, segment=(0.0, 2.0))


def _live() -> _Source:
    clip = make_clip("live-1", width=640, height=360, duration=3, file_created_at=TAKEN)
    clip.asset.type = AssetType.IMAGE
    clip.asset.original_file_name = "live-1.jpg"
    clip.asset.checksum = "sha1-live-1"
    clip.asset.live_photo_video_id = "companion-1"
    clip.live_burst_video_ids = ["burst-1", "burst-2"]
    # 3.0 s stitched: over the 2.5 s motion floor a Live clip needs to play (#2453).
    clip.live_burst_trim_points = [(0.0, 1.5), (0.0, 1.5)]
    directive = EditorialSelection("live-1", 0.0, 1.8, render_mode="motion")
    return _Source(clip, directive, segment=(0.0, 1.8))


def _render(source: _Source, run: Path, served, bank: PreparedSourceBank | None) -> AssemblyClip:
    config = Config()
    config.hardware.enabled = False
    config.tier = "basic"
    config.photos.duration = source.photo_seconds
    if source.hdr:
        config.output.codec = "h265"
        config.output.hdr_mode = HdrMode.HDR
    params = GenerationParams(
        clips=[source.clip],
        output_path=run / "film.mp4",
        config=config,
        client=_Immich(served),
        output_canvas=source.canvas,
        clip_segments={} if source.segment is None else {source.clip.asset.id: source.segment},
        editorial_selections=() if source.directive is None else (source.directive,),
    )
    run.mkdir(parents=True, exist_ok=True)
    [prepared] = extract_clips(params, None, run, prepared_sources=bank)
    return prepared


def _held_longer(source: _Source) -> None:
    source.photo_seconds = 3.0


def _hold_from_editor(source: _Source) -> None:
    source.directive = EditorialSelection("photo-1", 0.0, 3.5)
    source.segment = (0.0, 3.5)


def _portrait(source: _Source) -> None:
    source.canvas = OutputCanvas(360, 640, "portrait")


def _edited(source: _Source) -> None:
    source.clip.asset.is_edited = True


def _hdr_film(source: _Source) -> None:
    source.hdr = True


def _kept_as_still(source: _Source) -> None:
    source.directive = EditorialSelection("live-1", 0.0, 1.8, render_mode="still")


def _no_live_photos(source: _Source) -> None:
    # What `--no-live-photos` hands preparation: the picture without its burst.
    source.clip.live_burst_video_ids = None
    source.clip.live_burst_trim_points = None
    source.directive = None


def _later_take(source: _Source) -> None:
    source.clip.live_burst_trim_points = [(0.0, 1.5), (0.5, 2.0)]


def _other_window(source: _Source) -> None:
    source.segment = (1.0, 3.5)


# (source, the one change, whether the change shows in what assembly receives). An HDR
# film keeps a photo without a gain map in SDR, and another take of a burst runs as long:
# those must still be prepared again, but they look alike from outside.
CASES: dict[str, tuple[Callable[[], _Source], Callable[[_Source], None], bool]] = {
    "photo duration": (_photo, _held_longer, True),
    "the editor's hold": (_photo, _hold_from_editor, True),
    "the canvas": (_photo, _portrait, True),
    "the edited version": (_photo, _edited, True),
    "an HDR film": (_photo, _hdr_film, False),
    "a Live Photo kept as a still": (_live, _kept_as_still, True),
    "Live Photos turned off": (_live, _no_live_photos, True),
    "another take in the burst": (_live, _later_take, False),
    "another cut window": (_video_source, _other_window, True),
}


def _mean_rgb(path: Path, at: float) -> tuple[int, ...]:
    frame = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=30,
    ).stdout  # fmt: skip
    return tuple(frame[:3])


def _what_assembly_gets(clip: AssemblyClip) -> dict:
    probe = ProbeCache().get(clip.path)
    return {
        "is_photo": clip.is_photo,
        "duration": round(clip.duration, 2),
        "file_seconds": round(probe.duration_seconds, 1),
        "resolution": probe.resolution,
        "colour": _mean_rgb(clip.path, clip.duration / 2) if clip.is_photo else None,
    }


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_a_changed_input_is_prepared_again_and_the_film_gets_it(case, tmp_path, served):
    make, change, shows = case
    bank_dir = tmp_path / "bank"
    first = _render(
        make(), tmp_path / "run1", served, PreparedSourceBank(bank_dir, max_bytes=10**9)
    )

    changed = make()
    change(changed)
    bank = PreparedSourceBank(bank_dir, max_bytes=10**9)
    again = _render(changed, tmp_path / "run2", served, bank)
    fresh = make()
    change(fresh)
    reference = _render(fresh, tmp_path / "reference", served, None)

    assert (bank.taken, bank.kept) == (0, 1)
    assert _what_assembly_gets(again) == _what_assembly_gets(reference)
    if shows:
        assert _what_assembly_gets(again) != _what_assembly_gets(first)


def test_the_same_inputs_are_reused_and_give_the_same_clip(tmp_path, served):
    for make in (_photo, _live, _video_source):
        bank_dir = tmp_path / make.__name__ / "bank"
        first = _render(make(), tmp_path / make.__name__ / "run1", served,
                        PreparedSourceBank(bank_dir, max_bytes=10**9))  # fmt: skip
        bank = PreparedSourceBank(bank_dir, max_bytes=10**9)
        again = _render(make(), tmp_path / make.__name__ / "run2", served, bank)

        assert (bank.taken, bank.kept) == (1, 0), make.__name__
        assert _what_assembly_gets(again) == _what_assembly_gets(first)
