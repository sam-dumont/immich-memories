"""A film longer than one short take is joined from short ACE-Step takes (#2617).

Short takes joined on bar lines are the production recipe. One long generation per
film was an experiment that sounded bland and loop-flagged three times in a row
on a two-minute film, so the default never asks ACE-Step for more than a short take.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from immich_memories.audio.generators.ace_step_backend import ACE_TAKE_CAP_SECONDS
from immich_memories.audio.music_pipeline import MusicPipeline, _block_seconds
from immich_memories.config.loader import Config
from immich_memories.config.models.soundtrack import AudioConfig
from tests.test_music_one_piece import RecordingGenerator, _fake_join, _photo_film

SHORT_TAKE_SECONDS = 30


def test_the_default_take_is_short() -> None:
    assert AudioConfig().music_block_seconds == SHORT_TAKE_SECONDS
    assert _block_seconds(Config()) == SHORT_TAKE_SECONDS


async def test_a_two_minute_film_asks_ace_step_for_short_takes_and_joins_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    joined: list[dict[str, Any]] = []

    def join(takes, target, output, **kwargs):
        joined.append({"takes": list(takes), "target": target})
        return _fake_join(takes, target, output)

    # WHY: the bar-line join has its own integration test; this checks what it is given.
    monkeypatch.setattr("immich_memories.audio.music_pipeline.join_takes", join)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(36, film_seconds=128.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) > 1
    assert all(r.duration_seconds <= SHORT_TAKE_SECONDS for r in ace.requests)
    assert all(r.duration_limit_seconds <= SHORT_TAKE_SECONDS for r in ace.requests)
    assert len(joined) == 1
    assert len(joined[0]["takes"]) == len(ace.requests)
    assert joined[0]["target"] == pytest.approx(128.0, abs=1.5)


async def test_a_film_within_one_short_take_is_one_take(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ace = RecordingGenerator("ACE", max_take=ACE_TAKE_CAP_SECONDS)
    monkeypatch.setattr("immich_memories.audio.music_pipeline.join_takes", _fake_join)
    pipeline = MusicPipeline(generators=[ace], block_seconds=_block_seconds(Config()))

    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(6, film_seconds=24.0), output_dir=tmp_path, num_versions=1
        )

    assert len(ace.requests) == 1
