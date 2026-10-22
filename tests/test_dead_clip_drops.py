"""A clip that decodes to no frame leaves the film instead of freezing it (#2824).

An FFmpeg without a filter the clip's graph asks for (#2822), or a graph that
negotiates into one that never outputs a frame (#2792), used to leave the
assembler holding the frame before it for the clip's whole length. The clip
leaves, the film gets shorter (#2679), and the log says which and why.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.processing.assembly_config import AssemblyClip, AssemblySettings
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.film_timeline import FilmTimeline
from immich_memories.processing.streaming_frame_decoder import ClipGaveNoFrames


def _h264_plan() -> EncodingPlan:
    return EncodingPlan(
        codec=OutputCodec.H264,
        encoder="libx264",
        encoder_args=("-preset", "ultrafast", "-crf", "28"),
        target_transfer=HdrTransfer.NONE,
        tone_map_to_sdr=False,
        pixel_format="yuv420p",
        container="mp4",
    )


def _tiny_clip(path: Path) -> Path:
    subprocess.run(  # noqa: S603, S607
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


@pytest.fixture
def filter_this_ffmpeg_lacks(monkeypatch):
    """Clips named ``broken.mp4`` ask for a filter FFmpeg doesn't have, as drawtext did (#2822)."""
    from immich_memories.processing.streaming_frame_decoder import FrameDecoder

    build_vf = FrameDecoder._build_vf

    def lacking(self) -> str:
        graph = build_vf(self)
        return f"{graph},no_such_filter" if self._clip_path.name == "broken.mp4" else graph

    monkeypatch.setattr(FrameDecoder, "_build_vf", lacking)


@pytest.mark.usefixtures("filter_this_ffmpeg_lacks")
def test_the_assembler_names_a_clip_whose_decoder_gives_no_frame(tmp_path: Path) -> None:
    from immich_memories.processing.streaming_assembler import assemble_streaming

    broken = _tiny_clip(tmp_path / "broken.mp4")
    clips = [
        AssemblyClip(path=_tiny_clip(tmp_path / "a.mp4"), duration=1.0, asset_id="a"),
        AssemblyClip(path=broken, duration=1.0, asset_id="broken"),
        AssemblyClip(path=_tiny_clip(tmp_path / "c.mp4"), duration=1.0, asset_id="c"),
    ]

    with pytest.raises(ClipGaveNoFrames) as raised:
        assemble_streaming(
            clips=clips,
            transitions=["fade", "cut"],
            output_path=tmp_path / "film.mp4",
            width=160,
            height=120,
            fps=10,
            fade_duration=0.3,
            encoding_plan=_h264_plan(),
        )

    assert raised.value.index == 1
    assert "no_such_filter" in raised.value.why


def _engine(tmp_path: Path, **settings: object):
    from immich_memories.processing.assembly_engine import AssemblyEngine

    assembly = AssemblySettings(
        encoding_plan=_h264_plan(),
        auto_resolution=False,
        target_resolution=(1920, 1080),
        **settings,  # type: ignore[arg-type]
    )
    prober = MagicMock()
    prober.detect_max_framerate.return_value = 30
    return AssemblyEngine(assembly, prober, MagicMock()), assembly


def _clips(tmp_path: Path, *names: str, title: str | None = None) -> list[AssemblyClip]:
    clips = []
    for name in names:
        path = tmp_path / f"{name}.mp4"
        path.write_bytes(b"\x00" * 64)
        clips.append(
            AssemblyClip(
                path=path,
                duration=3.0,
                asset_id=name,
                is_title_screen=name == title,
            )
        )
    return clips


def _dies_once(index: int, why: str = "FFmpeg (exit 8) said: No such filter: 'drawtext'"):
    calls: list[dict] = []

    def assemble(**kwargs: object) -> Path:
        calls.append(kwargs)
        if len(calls) == 1:
            raise ClipGaveNoFrames(index, why)
        return kwargs["output_path"]  # type: ignore[return-value]

    return assemble, calls


def test_the_engine_assembles_again_without_the_clip_and_records_it(tmp_path, caplog) -> None:
    engine, settings = _engine(tmp_path)
    clips = _clips(tmp_path, "one", "two", "three")
    assemble, calls = _dies_once(1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with (
        patch(
            "immich_memories.processing.assembly_engine.streaming_assemble_full",
            side_effect=assemble,
        ),
        caplog.at_level(logging.WARNING),
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    assert [clip.asset_id for clip in calls[1]["clips"]] == ["one", "three"]
    assert len(calls[1]["transitions"]) == 1
    assert [clip.asset_id for clip in settings.undecodable_clips] == ["two"]
    assert "two.mp4" in caplog.text
    assert "drawtext" in caplog.text
    assert "3.0 s shorter" in caplog.text


def test_the_composed_transitions_lose_the_dropped_clip_boundary(tmp_path) -> None:
    engine, settings = _engine(tmp_path, predecided_transitions=["cut", "fade", "cut"])
    clips = _clips(tmp_path, "title", "one", "two", "three", title="title")
    assemble, calls = _dies_once(2)

    # WHY: the engine's retry is under test; the encode itself is not.
    with patch(
        "immich_memories.processing.assembly_engine.streaming_assemble_full",
        side_effect=assemble,
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    # The fade into the dropped clip now leads into the clip after it.
    assert calls[1]["transitions"] == ["cut", "fade"]
    assert settings.predecided_transitions == ["cut", "fade", "cut"]


def test_a_title_card_that_gives_no_frame_still_stops_the_film(tmp_path) -> None:
    engine, _settings = _engine(tmp_path)
    clips = _clips(tmp_path, "title", "one", "two", title="title")
    assemble, _calls = _dies_once(0)

    # WHY: the engine's retry is under test; the encode itself is not.
    with (
        patch(
            "immich_memories.processing.assembly_engine.streaming_assemble_full",
            side_effect=assemble,
        ),
        pytest.raises(ClipGaveNoFrames),
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")


def test_a_film_whose_every_clip_gives_no_frame_stops(tmp_path) -> None:
    engine, _settings = _engine(tmp_path)
    clips = _clips(tmp_path, "one", "two")

    def assemble(**kwargs: object) -> Path:
        raise ClipGaveNoFrames(0, "FFmpeg (exit 1) said: Invalid data")

    # WHY: the engine's retry is under test; the encode itself is not.
    with (
        patch(
            "immich_memories.processing.assembly_engine.streaming_assemble_full",
            side_effect=assemble,
        ),
        pytest.raises(ClipGaveNoFrames),
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")


def test_the_run_cut_no_longer_lists_a_dropped_source() -> None:
    from immich_memories.generate_render import without_undecodable_clips

    kept = AssemblyClip(path=Path("kept.mp4"), duration=4.0, asset_id="kept")
    gone = AssemblyClip(path=Path("gone.mp4"), duration=2.5, asset_id="gone")
    params = SimpleNamespace(departed_sources=("earlier",))
    settings = AssemblySettings(
        encoding_plan=_h264_plan(),
        undecodable_clips=[gone],
        film_timeline=FilmTimeline(10.0, 3.0, 0.0),
    )

    clips = without_undecodable_clips(params, [kept, gone], settings)

    assert clips == [kept]
    assert params.departed_sources == ("earlier", "gone")
    assert settings.film_timeline == FilmTimeline(7.5, 3.0, 0.0)


@pytest.mark.usefixtures("filter_this_ffmpeg_lacks")
def test_a_film_with_a_clip_that_gives_no_frame_comes_out_shorter(tmp_path: Path) -> None:
    import json

    from immich_memories.processing.video_assembler import VideoAssembler

    broken = _tiny_clip(tmp_path / "broken.mp4")
    clips = [
        AssemblyClip(path=_tiny_clip(tmp_path / "a.mp4"), duration=1.0, asset_id="a"),
        AssemblyClip(path=broken, duration=1.0, asset_id="broken"),
        AssemblyClip(path=_tiny_clip(tmp_path / "c.mp4"), duration=1.0, asset_id="c"),
    ]
    settings = AssemblySettings(
        encoding_plan=_h264_plan(),
        auto_resolution=False,
        target_resolution=(160, 120),
        transition_duration=0.2,
    )

    film = VideoAssembler(settings).assemble(clips, tmp_path / "film.mp4")

    probe = subprocess.run(  # noqa: S603, S607
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(film)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    # Two one-second clips, less at most one fade: the broken one is not held for its second.
    assert 1.6 < float(json.loads(probe.stdout)["format"]["duration"]) < 2.2
    assert [clip.asset_id for clip in settings.undecodable_clips] == ["broken"]
