"""Consuming the last required picture must also finish its audio output."""

import subprocess
import sys
import time
import wave
from types import SimpleNamespace

import pytest

from immich_memories.processing import streaming_frame_decoder as decoder_module
from tests.integration.conftest import requires_ffmpeg


@pytest.mark.parametrize("read_ahead", [None, False, True])
def test_last_required_frame_finishes_the_delayed_audio_child(tmp_path, monkeypatch, read_ahead):
    audio = tmp_path / "clip_0_audio.wav"
    child = (
        "import os,time,wave,sys; "
        "os.write(1,bytes(24)); time.sleep(0.15); "
        "w=wave.open(sys.argv[1],'wb'); w.setnchannels(2); "
        "w.setsampwidth(2); w.setframerate(48000); "
        "w.writeframes(bytes(3200*4)); w.close()"
    )
    real_popen = subprocess.Popen
    spawned = []
    commands = []

    def start(cmd, **kwargs):
        commands.append(cmd)
        process = real_popen([sys.executable, "-c", child, str(audio)], **kwargs)
        spawned.append(process)
        return process

    # WHY: a real child writes pictures before its WAV, making the shutdown
    # race deterministic while still proving file completion and child reaping.
    monkeypatch.setattr(decoder_module.subprocess, "Popen", start)
    # WHY: the child supplies the audio transport; probing a source file is
    # unrelated to whether the decoder waits for that transport to finish.
    monkeypatch.setattr(decoder_module.FrameDecoder, "_audio_input", lambda _self: ([], "0:a?"))
    clip = SimpleNamespace(path=tmp_path / "source.mp4", duration=2 / 30)
    decoder = decoder_module.make_decoder(clip, 0, 2, 2, 30, audio_work_dir=tmp_path)
    frames = (
        iter(decoder) if read_ahead is None else decoder.iter_borrowed_frames(read_ahead=read_ahead)
    )
    try:
        next(frames)
        next(frames)
        # The assembler closes immediately after the last requested picture.
        # Previously that SIGTERM discarded audio still being written.
        assert audio.exists()
        with wave.open(str(audio)) as output:
            assert output.getnframes() == 3200
        assert spawned[0].poll() == 0
    finally:
        frames.close()

    cmd = commands[0]
    assert cmd[cmd.index("-frames:v") + 1] == "2"
    assert float(cmd[cmd.index("-t") + 1]) == 2 / 30


@pytest.mark.parametrize("read_ahead", [None, False, True])
def test_early_cancellation_still_stops_the_owned_decoder(tmp_path, monkeypatch, read_ahead):
    real_popen = subprocess.Popen
    spawned = []

    def start(_cmd, **kwargs):
        child = "import os,time; os.write(1,bytes(12)); time.sleep(30)"
        process = real_popen([sys.executable, "-c", child], **kwargs)
        spawned.append(process)
        return process

    # WHY: cancellation must reap an actual stalled producer; a process mock
    # cannot show whether a live child was left running after generator.close().
    monkeypatch.setattr(decoder_module.subprocess, "Popen", start)
    decoder = decoder_module.FrameDecoder(tmp_path / "source.mp4", 2, 2, 30, frame_limit=2)
    frames = (
        iter(decoder) if read_ahead is None else decoder.iter_borrowed_frames(read_ahead=read_ahead)
    )
    try:
        next(frames)
    finally:
        frames.close()
    assert spawned[0].poll() is not None


@requires_ffmpeg
@pytest.mark.parametrize("consumer_delay", [0, 0.005])
@pytest.mark.parametrize("read_ahead", [None, False, True])
def test_bounded_real_decoder_finishes_exact_seek_audio_before_last_frame(
    tmp_path, consumer_delay, read_ahead
):
    source = tmp_path / "source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=30:duration=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=731:sample_rate=48000:duration=1.5",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    reference = tmp_path / "reference.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "0.25",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-t",
            "0.5",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(reference),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    clip = SimpleNamespace(path=source, duration=0.5, input_seek=0.25)
    decoder = decoder_module.make_decoder(clip, 0, 72, 128, 60, audio_work_dir=tmp_path)
    frames = (
        iter(decoder) if read_ahead is None else decoder.iter_borrowed_frames(read_ahead=read_ahead)
    )
    try:
        for _ in range(30):
            next(frames)
            time.sleep(consumer_delay)
        # Read before closing the suspended generator, exactly as the assembler
        # does when it has obtained every required video frame.
        with wave.open(str(tmp_path / "clip_0_audio.wav")) as audio:
            assert audio.getnframes() == 24000
            actual = audio.readframes(24000)
        with wave.open(str(reference)) as audio:
            assert actual == audio.readframes(24000)
    finally:
        frames.close()
