"""Music mood follows the synthetic saved cut through its normal text reader."""

import asyncio
import json
from functools import partial

from immich_memories.audio.text_mood import mood_for_cut
from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
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


def music_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case("music mood", partial(music_mood, llm), frozenset({"audio.text_mood:mood_for_cut"})),
    )
