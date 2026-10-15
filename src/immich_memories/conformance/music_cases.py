"""Music mood follows the synthetic saved cut through its normal text reader."""

import asyncio
import json
from functools import partial

from immich_memories.audio.text_mood import mood_for_cut
from immich_memories.config.loader import Config
from immich_memories.config.models.llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_store
from immich_memories.conformance.runtime import Case


def music_mood(llm: LLMConfig) -> str:
    with scratch_store() as (root, store):
        config = Config(
            llm=llm, database={"url": store.location.url}, cache={"directory": str(root / "cache")}
        )
        (root / "plan.private.json").write_text(
            json.dumps(
                {
                    "story": {
                        "thesis": "A quiet, peaceful afternoon: reading beside a still lake, leaves drifting slowly."
                    }
                }
            )
        )
        answer = asyncio.run(mood_for_cut(config, root, ()))
    assert answer.source == "cut_text", "music mood silently used the local fallback"
    assert answer.mood.primary_mood in {"calm", "peaceful", "relaxed"}, (
        "quiet cut received an unrelated mood"
    )
    assert answer.mood.energy_level == "low", "quiet cut received high-energy music"
    return "quiet cut gets a calm, low-energy mood from the model"


def lively_music_mood(llm: LLMConfig) -> str:
    """A birthday cut full of motion must not be read as calm (#2471)."""
    with scratch_store() as (root, store):
        config = Config(
            llm=llm, database={"url": store.location.url}, cache={"directory": str(root / "cache")}
        )
        kinds = ["video", "still", "live-motion", "video", "still", "video"]
        (root / "plan.private.json").write_text(
            json.dumps(
                {
                    "story": {
                        "thesis": "A birthday party in the garden: children run after balloons, "
                        "a cake with candles, everyone sings.",
                        "episodes": [
                            {"episode": "party", "weight": "major", "occasion": "birthday"}
                        ],
                    },
                    "carriers": [
                        {"asset_id": f"p{i}", "kind": kind, "taken": "2030-07-12T15:00:00"}
                        for i, kind in enumerate(kinds)
                    ],
                    "render_timing": {"policy": {"memory_type": "special_day"}},
                }
            )
        )
        answer = asyncio.run(mood_for_cut(config, root, ()))
    assert answer.source == "cut_text", "music mood silently used the local fallback"
    assert answer.mood.primary_mood not in {"calm", "peaceful", "sad", "melancholic"}, (
        "lively birthday cut received a quiet mood"
    )
    assert answer.mood.energy_level in {"medium", "high"}, "lively cut received low-energy music"
    return "lively birthday cut gets a medium or high energy mood from the model"


def music_cases(llm: LLMConfig) -> tuple[Case, ...]:
    site = frozenset({"audio.text_mood:mood_for_cut"})
    return (
        Case("music mood", partial(music_mood, llm), site),
        Case("lively music mood", partial(lively_music_mood, llm), site),
    )
