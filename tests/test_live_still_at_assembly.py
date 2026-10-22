"""A Live Photo whose motion decodes to no frame at assembly plays as its still (#2827).

Preparation already swaps a Live Photo whose certified motion fails for its own still
(#2679). A motion clip that passed preparation but gives no frame when the film is
assembled used to leave the film instead (#2824). The still holds the same slot, so
the timeline, the music and the captions don't move; only a still that fails too
lets the picture leave.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.processing.assembly_config import AssemblyClip, AssemblySettings
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
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


def _tiny_clip(path: Path, source: str = "testsrc2=") -> Path:
    subprocess.run(  # noqa: S603, S607
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"{source}size=160x120:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


def _engine(**settings: object):
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


def _clips(tmp_path: Path, *names: str) -> list[AssemblyClip]:
    clips = []
    for name in names:
        path = tmp_path / f"{name}.mp4"
        path.write_bytes(b"\x00" * 64)
        clips.append(AssemblyClip(path=path, duration=3.0, asset_id=name, date="2024-05-01"))
    return clips


def _still_of(tmp_path: Path):
    calls: list[AssemblyClip] = []

    def stand_in(dead: AssemblyClip) -> AssemblyClip | None:
        calls.append(dead)
        path = tmp_path / f"{dead.asset_id}-still.mp4"
        path.write_bytes(b"\x00" * 64)
        return AssemblyClip(
            path=path, duration=dead.duration, asset_id=dead.asset_id, is_photo=True
        )

    return stand_in, calls


def _dies(*indices: int, why: str = "FFmpeg (exit 8) said: No such filter: 'drawtext'"):
    calls: list[dict] = []

    def assemble(**kwargs: object) -> Path:
        calls.append(kwargs)
        if len(calls) <= len(indices):
            raise ClipGaveNoFrames(indices[len(calls) - 1], why)
        return kwargs["output_path"]  # type: ignore[return-value]

    return assemble, calls


def test_a_dead_live_motion_plays_as_its_still_in_the_same_slot(tmp_path, caplog) -> None:
    stand_in, asked = _still_of(tmp_path)
    engine, settings = _engine(stand_in=stand_in)
    clips = _clips(tmp_path, "one", "two", "three")
    assemble, calls = _dies(1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with (
        patch(
            "immich_memories.processing.assembly_engine.streaming_assemble_full",
            side_effect=assemble,
        ),
        caplog.at_level(logging.WARNING),
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    again = calls[1]["clips"]
    assert [clip.asset_id for clip in again] == ["one", "two", "three"]
    assert again[1].path.name == "two-still.mp4"
    assert again[1].is_photo
    assert again[1].duration == 3.0
    assert len(calls[1]["transitions"]) == 2
    assert [clip.asset_id for clip in asked] == ["two"]
    assert settings.undecodable_clips == []
    assert settings.stood_in["two"].path.name == "two-still.mp4"
    assert "two.mp4" in caplog.text
    assert "plays as its still" in caplog.text


def test_the_still_keeps_the_dead_clips_caption_and_place(tmp_path) -> None:
    (tmp_path / "still.mp4").write_bytes(b"\x00" * 64)

    def bare_still(dead: AssemblyClip) -> AssemblyClip:
        return AssemblyClip(
            path=tmp_path / "still.mp4", duration=2.0, asset_id=dead.asset_id, is_photo=True
        )

    engine, settings = _engine(stand_in=bare_still)
    clips = _clips(tmp_path, "one", "two")
    clips[1].location_name = "Somewhere"
    clips[1].caption_location_name = ""
    clips[1].outgoing_transition = "cut"
    clips[1].has_music = True
    assemble, calls = _dies(1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with patch(
        "immich_memories.processing.assembly_engine.streaming_assemble_full",
        side_effect=assemble,
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    still = calls[1]["clips"][1]
    assert still.path.name == "still.mp4"
    assert still.duration == 3.0  # the slot, not whatever the still came out at
    assert (still.date, still.location_name, still.caption_location_name) == (
        "2024-05-01",
        "Somewhere",
        "",
    )
    assert still.outgoing_transition == "cut"
    assert still.is_photo
    assert not still.has_music  # a still carries no sound of its own


def test_a_clip_with_no_still_leaves_the_film_as_before(tmp_path) -> None:
    engine, settings = _engine(stand_in=lambda _dead: None)
    clips = _clips(tmp_path, "one", "two", "three")
    assemble, calls = _dies(1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with patch(
        "immich_memories.processing.assembly_engine.streaming_assemble_full",
        side_effect=assemble,
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    assert [clip.asset_id for clip in calls[1]["clips"]] == ["one", "three"]
    assert [clip.asset_id for clip in settings.undecodable_clips] == ["two"]
    assert settings.stood_in == {}


def test_a_still_that_gives_no_frame_too_lets_the_picture_leave(tmp_path, caplog) -> None:
    stand_in, asked = _still_of(tmp_path)
    engine, settings = _engine(stand_in=stand_in)
    clips = _clips(tmp_path, "one", "two", "three")
    assemble, calls = _dies(1, 1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with (
        patch(
            "immich_memories.processing.assembly_engine.streaming_assemble_full",
            side_effect=assemble,
        ),
        caplog.at_level(logging.WARNING),
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    assert len(asked) == 1  # one still per picture, never a loop
    assert [clip.asset_id for clip in calls[2]["clips"]] == ["one", "three"]
    assert [clip.asset_id for clip in settings.undecodable_clips] == ["two"]
    assert settings.stood_in == {}
    assert "leaves the film" in caplog.text


def test_a_photo_that_gives_no_frame_is_not_offered_a_still(tmp_path) -> None:
    stand_in, asked = _still_of(tmp_path)
    engine, settings = _engine(stand_in=stand_in)
    clips = _clips(tmp_path, "one", "two", "three")
    clips[1].is_photo = True
    assemble, _calls = _dies(1)

    # WHY: the engine's retry is under test; the encode itself is not.
    with patch(
        "immich_memories.processing.assembly_engine.streaming_assemble_full",
        side_effect=assemble,
    ):
        engine.assemble_scalable(clips, tmp_path / "memory.mp4")

    assert asked == []
    assert [clip.asset_id for clip in settings.undecodable_clips] == ["two"]


def _live_source(asset_id: str, *, live: bool):
    from immich_memories.api.models import AssetType

    return SimpleNamespace(
        asset=SimpleNamespace(id=asset_id, type=AssetType.IMAGE if live else AssetType.VIDEO),
        editorial_live_manifest={"selected_interval": [0.5, 3.5]} if live else None,
    )


def _params(tmp_path: Path, *sources: object):
    from immich_memories.config.loader import Config
    from immich_memories.generate import GenerationParams

    return GenerationParams(
        clips=list(sources), output_path=tmp_path / "memory.mp4", config=Config()
    )


def test_the_run_offers_a_still_only_for_a_live_photo(tmp_path) -> None:
    from immich_memories.generate_render import live_still_stand_in

    params = _params(tmp_path, _live_source("live", live=True), _live_source("video", live=False))
    rendered = AssemblyClip(path=tmp_path / "s.mp4", duration=3.0, asset_id="live", is_photo=True)
    settings = AssemblySettings(encoding_plan=_h264_plan())

    # WHY: which picture the run renders, and for how long, is under test.
    with patch(
        "immich_memories.generate_photos.render_photo_as_clip", return_value=rendered
    ) as render:
        stand_in = live_still_stand_in(params, [], tmp_path, settings)
        assert stand_in(AssemblyClip(path=Path("v.mp4"), duration=2.0, asset_id="video")) is None
        still = stand_in(AssemblyClip(path=Path("l.mp4"), duration=3.0, asset_id="live"))

    assert still is rendered
    render.assert_called_once()
    assert render.call_args.args[0] is params.clips[0]
    assert render.call_args.kwargs["duration_seconds"] == 3.0
    assert render.call_args.args[1].photo_fps == 30


def test_a_still_the_run_cannot_render_leaves_it_to_the_drop(tmp_path) -> None:
    from immich_memories.generate_render import live_still_stand_in

    params = _params(tmp_path, _live_source("live", live=True))
    settings = AssemblySettings(encoding_plan=_h264_plan())

    # WHY: a failing photo render is the case under test.
    with patch(
        "immich_memories.generate_photos.render_photo_as_clip",
        side_effect=OSError("download failed"),
    ):
        stand_in = live_still_stand_in(params, [], tmp_path, settings)
        assert stand_in(AssemblyClip(path=Path("l.mp4"), duration=3.0, asset_id="live")) is None


def test_the_run_cut_carries_the_still_where_the_motion_was() -> None:
    from immich_memories.generate_render import with_stand_ins

    motion = AssemblyClip(path=Path("motion.mp4"), duration=3.0, asset_id="live")
    other = AssemblyClip(path=Path("other.mp4"), duration=2.0, asset_id="other")
    still = AssemblyClip(path=Path("still.mp4"), duration=3.0, asset_id="live", is_photo=True)
    settings = AssemblySettings(encoding_plan=_h264_plan(), stood_in={"live": still})

    assert with_stand_ins([other, motion], settings) == [other, still]


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
def test_a_film_whose_live_motion_dies_keeps_its_length_with_the_still(tmp_path: Path) -> None:
    from immich_memories.processing.video_assembler import VideoAssembler

    still = _tiny_clip(tmp_path / "still.mp4", source="color=c=red:")

    def stand_in(dead: AssemblyClip) -> AssemblyClip:
        return AssemblyClip(
            path=still, duration=dead.duration, asset_id=dead.asset_id, is_photo=True
        )

    clips = [
        AssemblyClip(path=_tiny_clip(tmp_path / "a.mp4"), duration=1.0, asset_id="a"),
        AssemblyClip(path=_tiny_clip(tmp_path / "broken.mp4"), duration=1.0, asset_id="live"),
        AssemblyClip(path=_tiny_clip(tmp_path / "c.mp4"), duration=1.0, asset_id="c"),
    ]
    settings = AssemblySettings(
        encoding_plan=_h264_plan(),
        auto_resolution=False,
        target_resolution=(160, 120),
        transition_duration=0.2,
        stand_in=stand_in,
    )

    film = VideoAssembler(settings).assemble(clips, tmp_path / "film.mp4")

    probe = subprocess.run(  # noqa: S603, S607
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(film)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    # Three one-second slots, less at most two fades: the still kept the Live Photo's.
    assert 2.5 < float(json.loads(probe.stdout)["format"]["duration"]) < 3.2
    assert settings.undecodable_clips == []
    assert settings.stood_in["live"].path == still
    # The middle second shows the red still, not a frozen frame of the clip before it.
    middle = subprocess.run(  # noqa: S603, S607
        [
            "ffmpeg",
            "-v",
            "quiet",
            "-ss",
            "1.5",
            "-i",
            str(film),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        timeout=30,
        check=True,
    ).stdout
    red, green, blue = middle[:3]
    assert red > 150 > max(green, blue)
