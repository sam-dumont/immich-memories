"""Both soundtrack providers receive the frame cadence of the finished film."""

from unittest.mock import create_autospec

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import run_music_phase
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.tracking.run_tracker import RunTracker
from tests.test_music_video_duration import _h264_plan


@pytest.mark.parametrize(
    "fps, cadence_frames", [(24, 78), (25, 81), (29.97, 98), (30, 97), (60, 195)]
)
@pytest.mark.parametrize("provider", ["bundled", "generated"])
def test_soundtrack_cadence_uses_the_finished_films_frame_rate(
    tmp_path, monkeypatch, fps, cadence_frames, provider
):
    import subprocess

    film = tmp_path / "film.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s=32x32:r={fps}:d=1",
            str(film),
        ],
        check=True,
        capture_output=True,
    )
    clips = [AssemblyClip(film, 3.751, is_photo=True) for _ in range(3)]
    seen = []

    def bundled(_mood, **kwargs):
        seen.append(("bundled", kwargs["cadence_seconds"]))
        return []

    async def generated(**kwargs):
        seen.append(("generated", kwargs["photo_cadence_seconds"]))
        return None

    # WHY: stop at the installed-track and model backends; no library or model is needed
    # to observe the timing request. The music phase, probing and provider routing are real.
    monkeypatch.setattr("immich_memories.audio.bundled_music.bundled_playlist_for_mood", bundled)
    monkeypatch.setattr("immich_memories.audio.music_generator.generate_music_for_video", generated)
    config = Config()
    config.ace_step.enabled = provider == "generated"
    config.musicgen.enabled = False
    # WHY: run history writes are outside the soundtrack timing contract.
    tracker = create_autospec(RunTracker, instance=True)
    result = run_music_phase(
        GenerationParams(clips=[], output_path=film, config=config),
        clips,
        film,
        tmp_path,
        tracker,
        encoding_plan=_h264_plan(),
    )

    assert result.warning is None
    assert (provider, pytest.approx(cadence_frames / fps)) in seen
