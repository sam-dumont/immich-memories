"""A music-only film contains none of the original recording."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing.assembly_config import standalone_assembly_encoding_plan
from immich_memories.processing.output_contract import check_output
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def source(path: Path) -> None:
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=32x32:r=30:d=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=48000:duration=3",
        "-vf",
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-color_trc",
        "bt709",
        "-color_primaries",
        "bt709",
        "-colorspace",
        "bt709",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )


def samples(path: Path) -> np.ndarray:
    return np.frombuffer(
        ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"),
        dtype=np.float32,
    )


def test_muting_removes_original_recording_without_changing_picture_or_timing(tmp_path):
    from immich_memories.generate_music import mute_original_audio

    film = tmp_path / "film.mp4"
    source(film)
    plan = standalone_assembly_encoding_plan(18)
    before = check_output(film, plan)
    picture = ffmpeg("-i", str(film), "-map", "0:v:0", "-c:v", "copy", "-f", "hash", "-")
    assert np.max(np.abs(samples(film))) > 0.05

    mute_original_audio(film, plan)

    assert np.max(np.abs(samples(film))) < 1e-7
    assert ffmpeg("-i", str(film), "-map", "0:v:0", "-c:v", "copy", "-f", "hash", "-") == picture
    assert abs(check_output(film, plan).duration_seconds - before.duration_seconds) < 1 / 30


@pytest.mark.parametrize(
    "original_audio, music, failure",
    [
        (False, True, False),
        (False, False, False),
        (True, False, False),
        (False, True, True),
    ],
)
def test_shared_render_finalization_obeys_source_audio_choice(
    tmp_path, monkeypatch, original_audio, music, failure
):
    import shutil

    from immich_memories.db import open_store
    from immich_memories.generate import (
        GenerationError,
        GenerationParams,
        PreparedGeneration,
        generate_memory,
    )
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.tracking import RunDatabase
    from tests.conftest import make_clip
    from tests.web_api_fixtures import config_in

    original = tmp_path / "original.mp4"
    source(original)
    track = tmp_path / "music.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=400:sample_rate=48000:duration=3", str(track))
    plan = standalone_assembly_encoding_plan(18)
    config = config_in(tmp_path)
    clip = make_clip("source-clip", duration=3, width=32, height=32)

    def assembled(_params, output, *_args):
        staged = output.with_name("staged.mp4")
        shutil.copyfile(original, staged)
        return PreparedGeneration(
            path=output,
            staged_path=staged,
            encoding_plan=plan,
            assembly_clips=(AssemblyClip(path=original, duration=3),),
            clips_analyzed=1,
            clips_selected=1,
            music_mute_windows=[(0, 3)],
        )

    # WHY: the local/GPU rendering boundary returns the same real assembled film;
    # final audio handling, validation and run persistence remain real.
    monkeypatch.setattr("immich_memories.generate_render.render_base", assembled)
    params = GenerationParams(
        clips=[clip],
        output_path=tmp_path / "film.mp4",
        config=config,
        original_audio=original_audio,
        music_path=track if music else None,
        no_music=not music,
        upload_enabled=failure,
    )
    if failure:
        real_run = subprocess.run

        def failing_mute(command, **kwargs):
            if "anullsrc=r=48000:cl=stereo" in command:
                raise subprocess.CalledProcessError(1, command, stderr=b"private recording")
            return real_run(command, **kwargs)

        # WHY: fail the FFmpeg I/O boundary only for muting; probes remain real.
        monkeypatch.setattr(subprocess, "run", failing_mute)
        with pytest.raises(GenerationError, match="Could not mute original audio"):
            generate_memory(params)
        run = RunDatabase(open_store(config)).list_runs()[0]
        assert run.status == "failed"
        assert run.delivery_status == "not_requested"
        assert run.output_path is None
        assert run.immich_asset_id is None
        return
    result = generate_memory(params)
    audio = samples(result)
    spectrum = np.abs(np.fft.rfft(audio[48000:96000])) / 48000
    if original_audio:
        assert spectrum[1000] > 0.01
    else:
        assert spectrum[1000] < 1e-5
        assert (spectrum[400] > 0.001) if music else np.max(np.abs(audio)) < 1e-7
    assert abs(check_output(result, plan).duration_seconds - 3) < 1 / 30
