"""Real FFmpeg frame extraction works when system temporary storage is unavailable."""

import tempfile

import pytest
from PIL import Image

from immich_memories.processing.frame_sampling import sample_frames
from immich_memories.security import runtime_scratch

pytestmark = pytest.mark.integration


def test_frame_extraction_uses_mounted_runtime_scratch(short_clip, tmp_path, monkeypatch):
    unavailable = tmp_path / "unavailable-system-temp"
    unavailable.write_text("system temporary storage cannot hold media")
    # WHY: emulate the full/unusable system volume; all media operations use real FFmpeg.
    monkeypatch.setattr(tempfile, "tempdir", str(unavailable))
    mounted = tmp_path / "mounted-cache"

    with runtime_scratch(mounted):
        frames = sample_frames(short_clip, count=3, width=160, cache_dir=None)
        assert len(frames) == 3
        for frame in frames:
            assert frame.is_relative_to(mounted)
            with Image.open(frame) as image:
                assert image.width == 160
                image.verify()

    assert tempfile.tempdir == str(unavailable)
    assert unavailable.is_file()
