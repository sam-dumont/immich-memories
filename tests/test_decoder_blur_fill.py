"""A clip that already fills the canvas gets no blur fill behind it (#1527)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories.processing.streaming_frame_decoder import FrameDecoder


def _filters(tmp_path, monkeypatch, source_size, rotation=0) -> str:
    started: list[list[str]] = []

    def launch(cmd, **_kwargs):
        started.append(cmd)
        raise OSError("not started")

    # WHY: the ffmpeg process is the boundary; the test reads the command it is given.
    monkeypatch.setattr(subprocess, "Popen", launch)
    decoder = FrameDecoder(
        Path(tmp_path / "clip.mov"),
        width=2160,
        height=3840,
        fps=30,
        scale_mode="blur",
        rotation=rotation,
        source_size=source_size,
    )
    with pytest.raises(OSError, match="not started"):
        next(iter(decoder))
    (cmd,) = started
    flag = "-filter_complex" if "-filter_complex" in cmd else "-vf"
    return cmd[cmd.index(flag) + 1]


@pytest.mark.parametrize("source", [(2160, 3840), (1080, 1920)])
def test_a_clip_with_the_canvas_shape_builds_no_blur_fill(tmp_path, monkeypatch, source):
    filters = _filters(tmp_path, monkeypatch, source)
    assert "gblur" not in filters
    assert "overlay" not in filters
    assert "scale=2160:3840" in filters


def test_a_landscape_clip_turned_upright_fills_the_canvas_too(tmp_path, monkeypatch):
    assert "gblur" not in _filters(tmp_path, monkeypatch, (3840, 2160), rotation=90)


@pytest.mark.parametrize("source", [(3840, 2160), (3024, 4032), None])
def test_a_letterboxed_or_unprobed_clip_keeps_the_blur_fill(tmp_path, monkeypatch, source):
    filters = _filters(tmp_path, monkeypatch, source)
    assert "gblur=sigma=30" in filters
    assert "overlay" in filters
