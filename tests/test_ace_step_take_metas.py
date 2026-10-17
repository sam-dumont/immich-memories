"""What ACE-Step is told beyond the caption: key, meter and its planner switches.

One take leaves key and meter to the model; joined takes pin them so their seams agree
(that half is `test_music_one_piece`). API mode turns the server's planner off unless
`use_lm` asks for it, so a server with a planner loaded does not rewrite the caption.
"""

from __future__ import annotations

import pytest

from immich_memories.audio.music_pipeline import MusicPipeline
from tests.test_ace_step_block_duration import ace_boundary  # noqa: F401 - pytest fixture
from tests.test_music_one_piece import _photo_film


async def _one_take_film(backend, tmp_path) -> None:
    pipeline = MusicPipeline(generators=[backend], block_seconds=240, max_blocks=3)
    async with pipeline:
        await pipeline.generate_music_for_video(
            timeline=_photo_film(40, film_seconds=150.0), output_dir=tmp_path, num_versions=1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["lib", "api"])
async def test_a_one_take_film_pins_key_and_meter(
    mode,
    tmp_path,
    ace_boundary,  # noqa: F811 - pytest fixture
):
    backend, captured = ace_boundary(mode)

    await _one_take_film(backend, tmp_path)

    assert len(captured) == 1
    assert captured[0]["keyscale"]
    assert captured[0]["timesignature"] == "4"
    assert captured[0]["bpm"], "tempo stays pinned: the photo cuts are on its beat"


@pytest.mark.asyncio
async def test_api_mode_turns_the_servers_planner_off_by_default(
    tmp_path,
    ace_boundary,  # noqa: F811 - pytest fixture
):
    backend, captured = ace_boundary("api")

    await _one_take_film(backend, tmp_path)

    sent = captured[0]
    assert sent["thinking"] is False
    assert sent["use_cot_caption"] is False
    assert sent["use_cot_metas"] is False
    assert sent["use_cot_language"] is False


@pytest.mark.asyncio
async def test_use_lm_still_hands_the_caption_to_the_servers_planner(
    tmp_path,
    ace_boundary,  # noqa: F811 - pytest fixture
):
    backend, captured = ace_boundary("api")
    backend.config.use_lm = True

    await _one_take_film(backend, tmp_path)

    sent = captured[0]
    assert sent["thinking"] is True
    assert sent["use_cot_caption"] is True
    assert sent["use_cot_metas"] is True
