"""An episode reading is one entry per episode, never one per picture.

Three films of three on a small local model ran out of tokens the same way: handed one
episode of 35 to 54 pictures, the model wrote an `episodes` entry for every picture
("episode": 1, 2, 3 ... N), at 60-85 tokens each, past a budget sized for one entry. The
budget was right; the prompt never said how many entries to write, and a local endpoint gets
no schema to say it instead. A reply that numbers more episodes than were asked was then
banked as if its first row, about one picture, described the whole episode.
"""

from __future__ import annotations

import json

from immich_memories.analysis.reading.episode_answers import (
    TEXT_EPISODE_SCHEMA_VERSION,
    EpisodeRequestScope,
    read_response_result,
)
from immich_memories.analysis.reading.episode_prompt import EpisodePromptFacts, episode_prompt
from immich_memories.store.episode_readings import EpisodeReadingIdentity


def _scope(key: str, assets: tuple[str, ...]) -> EpisodeRequestScope:
    return EpisodeRequestScope(
        identity=EpisodeReadingIdentity(group_id=key, producer_key="p", evidence_key="e"),
        full_asset_ids=assets,
        page_asset_ids=assets,
        page_number=1,
        page_count=1,
    )


def _row(alias: int) -> dict:
    return {
        "episode": alias,
        "what_happened": "A child plays in the garden",
        "representatives": [{"asset": 1, "reason": "child at play"}],
        "notable_moments": [],
    }


def test_the_prompt_asks_one_reading_of_the_whole_episode_whatever_the_pictures() -> None:
    """Since #2594 a request reads one episode and the answer is that reading, with no list of
    entries a model could fill one per picture."""
    pictures = tuple(f"a{i}" for i in range(40))
    lines = dict.fromkeys(pictures, "a child in a garden")

    for lean in (False, True):
        prompt = episode_prompt(_scope("e1", pictures), EpisodePromptFacts(lines, lean=lean))

        assert prompt.count("EPISODE: 40 pictures") == 1
        assert '"episodes"' not in prompt
        assert 'JSON only: {"what_happened"' in prompt


def test_a_reply_with_an_entry_per_picture_reads_no_episode() -> None:
    pictures = tuple(f"a{i}" for i in range(5))
    reply = json.dumps(
        {"schema_version": TEXT_EPISODE_SCHEMA_VERSION, "episodes": [_row(i) for i in range(1, 6)]}
    )

    result = read_response_result(reply, (_scope("e1", pictures),))

    assert result.readings == ()
    assert result.diagnostic is not None
    assert result.diagnostic.unreadable_or_omitted_pages == 1


def test_a_reply_with_one_entry_per_episode_still_reads() -> None:
    reply = json.dumps(
        {"schema_version": TEXT_EPISODE_SCHEMA_VERSION, "episodes": [_row(1), _row(2)]}
    )

    result = read_response_result(reply, (_scope("e1", ("a1",)), _scope("e2", ("a2",))))

    assert len(result.readings) == 2
