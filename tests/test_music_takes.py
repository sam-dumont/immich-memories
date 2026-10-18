"""Generated music comes in takes of up to 90 seconds, joined on bar lines.

The music library was generated as 90 s takes and they hold together, so a film that
fits in one take is one take, and a longer one is joined from takes of at most 90 s
that share one identity (#2617 started with 30 s takes; the library proved longer ones
fine). Every take is asked a margin past the music it must cover: a take ends on an
outro and then silence, and a single take asked for the film's own length went quiet
three to four seconds before the last frame.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from immich_memories.audio.generators.ace_step_backend import (
    ACE_TAKE_CAP_SECONDS,
    ACEStepBackend,
    ACEStepConfig,
)
from immich_memories.audio.generators.ace_step_mlx_handoff import install_mlx_memory_handoff
from immich_memories.audio.music_pipeline import MusicPipeline, _block_seconds
from immich_memories.config.loader import Config
from immich_memories.config.models.soundtrack import AudioConfig
from tests.generated_audio_fixtures import write_audio
from tests.test_music_one_piece import RecordingGenerator, _fake_join, _photo_film

TAKE_SECONDS = 90
JOIN_MARGIN = 8


def _recording_join(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []

    def join(takes, target, output, **kwargs):
        joined.append({"takes": list(takes), "target": target})
        return _fake_join(takes, target, output)

    # WHY: the bar-line join has its own integration test; this checks what it is given.
    monkeypatch.setattr("immich_memories.audio.music_pipeline.join_takes", join)
    return joined


def test_the_default_take_is_ninety_seconds() -> None:
    assert AudioConfig().music_block_seconds == TAKE_SECONDS
    assert _block_seconds(Config()) == TAKE_SECONDS


async def test_a_one_minute_film_is_one_take_that_runs_past_its_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    joined = _recording_join(monkeypatch)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(16, film_seconds=60.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) == 1
    assert ace.requests[0].duration_seconds == pytest.approx(60.0 + JOIN_MARGIN, abs=1.5)
    assert ace.requests[0].duration_limit_seconds == ace.requests[0].duration_seconds
    assert joined == []


async def test_a_film_whose_margin_would_pass_the_take_length_is_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    joined = _recording_join(monkeypatch)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(24, film_seconds=85.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) == 2
    assert all(r.duration_seconds <= TAKE_SECONDS for r in ace.requests)
    assert len(joined) == 1


async def test_a_150_second_film_is_two_takes_of_at_most_90_seconds_joined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    joined = _recording_join(monkeypatch)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(40, film_seconds=150.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) == 2
    assert all(r.duration_seconds <= TAKE_SECONDS for r in ace.requests)
    assert all(r.duration_limit_seconds <= TAKE_SECONDS for r in ace.requests)
    assert len(joined) == 1
    assert len(joined[0]["takes"]) == 2
    assert joined[0]["target"] == pytest.approx(150.0, abs=1.5)


async def test_a_film_past_three_takes_repeats_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    joined = _recording_join(monkeypatch)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(90, film_seconds=330.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) == 3
    assert all(r.duration_seconds == TAKE_SECONDS for r in ace.requests)
    assert joined[0]["target"] == pytest.approx(330.0, abs=1.5)


def _owned_mlx_runtime(tmp_path: Path) -> SimpleNamespace:
    """A runtime whose handler carries the real one-generation-per-handler guard."""
    handler = SimpleNamespace(
        generate_music=lambda: None,
        _load_main_model_from_checkpoint=lambda: None,
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=lambda: None,
    )
    assert install_mlx_memory_handoff(handler, tmp_path / "model.safetensors")

    def generate_music(*, dit_handler, llm_handler, params, config, save_dir):
        dit_handler.generate_music()
        out = Path(save_dir) / "upstream.wav"
        write_audio(out, 0.3)
        return SimpleNamespace(success=True, audios=[{"path": str(out)}])

    return SimpleNamespace(
        dit_handler=handler,
        llm_handler=None,
        generation_params_type=SimpleNamespace,
        generation_config_type=SimpleNamespace,
        generate_music=generate_music,
        device="cpu",
        lm_backend="mlx",
        dit_model="acestep-v15-turbo",
        lm_model=None,
    )


async def test_the_owned_mlx_handler_still_makes_every_take_of_a_long_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: the owned MLX handler allows one generation per handler; each take must load its own.
    runtimes: list[SimpleNamespace] = []

    def build(**_kwargs):
        runtimes.append(_owned_mlx_runtime(tmp_path))
        return runtimes[-1]

    module = "immich_memories.audio.generators.ace_step_backend"
    monkeypatch.setattr(f"{module}.ace_step_isolated.isolated_python", lambda: None)
    monkeypatch.setattr(f"{module}.is_ace_step_importable", lambda: True)
    monkeypatch.setattr(f"{module}.build_v15_runtime", build)
    monkeypatch.setattr(f"{module}.ACEStepV15Runtime", SimpleNamespace)
    monkeypatch.setattr(f"{module}.release_runtime_memory", lambda: None)
    joined = _recording_join(monkeypatch)
    backend = ACEStepBackend(ACEStepConfig(mode="lib", model_variant="turbo", use_lm=False))
    backend._effective_mode = "lib"
    pipeline = MusicPipeline(generators=[backend], block_seconds=_block_seconds(Config()))

    async with pipeline:
        result = await pipeline.generate_music_for_video(
            timeline=_photo_film(60, film_seconds=240.0), output_dir=tmp_path, num_versions=1
        )

    assert len(runtimes) == 3
    assert len(joined) == 1 and len(joined[0]["takes"]) == 3
    assert result.versions


def test_a_take_that_ends_in_silence_is_cut_while_it_still_plays(tmp_path: Path) -> None:
    """The one-take film's take: 64 s of music and 4 s of silence, cut to a 60 s film."""
    import wave

    import numpy as np

    from immich_memories.audio.take_join import RATE, trim_take

    rate = 24000
    music = 0.5 * np.sin(2 * np.pi * 220 * np.arange(64 * rate) / rate)
    take = np.concatenate([music, np.zeros(4 * rate)])
    source = tmp_path / "take.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes((take * 32767).astype("<i2").tobytes())

    cut = trim_take(source, 60.0, tmp_path / "cut.wav")

    with wave.open(str(cut), "rb") as audio:
        frames = audio.getnframes()
        samples = np.frombuffer(audio.readframes(frames), dtype="<i2").reshape(-1, 2)
    assert frames == 60 * RATE
    # Sound right up to the closing fade: the take's own silence falls after the cut.
    before_fade = samples[57 * RATE : 58 * RATE].astype(np.float32) / 32767
    assert np.sqrt(np.mean(before_fade**2)) > 0.1
