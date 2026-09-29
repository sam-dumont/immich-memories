"""Generated audio must be audible before mastering or stem separation."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from immich_memories.audio.generators.base import (
    GenerationRequest,
    GenerationResult,
    MusicGenerator,
)
from immich_memories.audio.music_generator_models import VideoTimeline
from immich_memories.audio.music_pipeline import MusicPipeline
from tests.generated_audio_fixtures import write_audio


class FixtureGenerator(MusicGenerator):
    """Replace the external generation service with an actual audio fixture."""

    def __init__(self, path: Path):
        self.path = path
        self.calls = 0

    @property
    def name(self) -> str:
        return self.path.stem

    async def is_available(self) -> bool:
        return True

    async def generate(
        self, request: GenerationRequest, progress_callback: Any | None = None
    ) -> GenerationResult:
        self.calls += 1
        return GenerationResult(audio_path=self.path, prompt=self.name)


@pytest.mark.asyncio
async def test_silent_generation_uses_audible_fallback(tmp_path, caplog):
    silent = tmp_path / "silent.wav"
    audible = tmp_path / "audible.wav"
    write_audio(silent, 0)
    write_audio(audible, 0.2)
    # WHY: replace only the external generators; decoding and mastering stay real.
    primary, fallback = FixtureGenerator(silent), FixtureGenerator(audible)
    result = await MusicPipeline([primary, fallback]).generate_music_for_video(
        VideoTimeline(), tmp_path, num_versions=1
    )
    assert result.versions[0].prompt == "audible"
    assert fallback.calls == 1
    assert "silent or near-silent" in caplog.text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.00001])
@pytest.mark.asyncio
async def test_invalid_samples_exhaust_generation(tmp_path, value):
    import struct

    samples = np.full(24000, value, dtype="<f4").tobytes()
    path = tmp_path / "invalid.wav"
    # IEEE float WAV preserves NaN/Inf instead of quantizing them to PCM silence.
    path.write_bytes(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(samples),
            b"WAVE",
            b"fmt ",
            16,
            3,
            1,
            24000,
            96000,
            4,
            32,
            b"data",
            len(samples),
        )
        + samples
    )
    # WHY: synthetic output replaces the external generation service.
    with pytest.raises(RuntimeError, match="All music generation backends failed"):
        await MusicPipeline([FixtureGenerator(path)]).generate_music_for_video(
            VideoTimeline(), tmp_path, num_versions=1
        )


@pytest.mark.asyncio
async def test_audible_generation_does_not_call_fallback(tmp_path):
    path = tmp_path / "audible.wav"
    write_audio(path, 0.2)
    # WHY: synthetic output replaces the external generation services.
    primary, fallback = FixtureGenerator(path), FixtureGenerator(path)
    result = await MusicPipeline([primary, fallback]).generate_music_for_video(
        VideoTimeline(), tmp_path, num_versions=1
    )
    assert len(result.versions) == 1
    assert primary.calls == 1
    assert fallback.calls == 0
