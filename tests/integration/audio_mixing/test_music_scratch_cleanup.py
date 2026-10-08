"""The finished film owns its audio; bundled mixing files are disposable work."""

import subprocess

import pytest

from immich_memories.config_loader import Config
from immich_memories.db import StoreLocation, open_store
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import run_music_phase
from immich_memories.tracking.run_tracker import RunTracker
from tests.integration.audio_mixing.test_bundled_music_mix import _write_tone
from tests.test_music_bundled_fallback import _h264_plan

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mix_fails", [False, True])
def test_bundled_playlist_is_mixed_without_leaving_scratch_audio(tmp_path, monkeypatch, mix_fails):
    output = tmp_path / "output"
    output.mkdir()
    film = output / "film.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=32x32:r=5:d=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=100:duration=5:sample_rate=44100",
            "-c:a",
            "aac",
            "-shortest",
            "-c:v",
            "libx264",
            "-vf",
            "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_range",
            "tv",
            str(film),
        ],
        check=True,
    )
    (output / "notes.txt").write_text("keep this file")
    tracks = [tmp_path / "first.wav", tmp_path / "second.wav"]
    for path, frequency in zip(tracks, [220, 440], strict=True):
        _write_tone(path, frequency, amplitude=0.4, duration=4)

    # WHY: the installed bundled library is external; playlist assembly, mastering and mixing run for real.
    monkeypatch.setattr("immich_memories.generate_music._bundled_sequence", lambda *_args: tracks)
    if mix_fails:

        def fail_mix(*_args, **_kwargs):
            raise OSError("mix failed")

        # WHY: a failed encoder must clean up the same temporary files as a successful mix.
        monkeypatch.setattr("immich_memories.generate_music.apply_music_file", fail_mix)
    store = open_store(location=StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}"))
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run()
    try:
        result = run_music_phase(
            GenerationParams(clips=[], output_path=film, config=Config()),
            [],
            film,
            output,
            tracker,
            encoding_plan=_h264_plan(),
        )
    finally:
        tracker.release_run()

    if mix_fails:
        assert not result.applied
        assert "mix failed" in result.warning
    else:
        assert result.applied, result.warning
        audio = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(film), "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True,
            check=True,
        )
        assert not audio.stderr
    assert sorted(p.name for p in output.iterdir()) == ["film.mp4", "notes.txt"]
    assert all(track.exists() for track in tracks)
