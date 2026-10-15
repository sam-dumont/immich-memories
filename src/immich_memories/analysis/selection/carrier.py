"""A picture's own story context, shared by draft selection and every later insertion."""

from collections.abc import Mapping, Sequence
from typing import Any

from immich_memories.analysis.facts.shot_reason import shot_reason_of_row
from immich_memories.analysis.stories.replies import WEIGHT_ROLE


def carrier_row(
    unit: Mapping[str, Any],
    *,
    family: str,
    anchor: str,
    story: Mapping[str, Any],
    chapter: int,
    line: str,
    siblings: Sequence[str] = (),
) -> dict[str, Any]:
    """Bind playable facts to their own story, never the outgoing picture's story.

    Its reason is the picture's own, in words: who is on it, what it shows, why it plays.
    `siblings` are the lines of the other frames of its moment, which it was chosen over.
    """
    title = str(story.get("title") or "")
    return dict(unit) | {
        "event": family,
        "anchor": anchor,
        "chapter": chapter,
        "why": shot_reason_of_row(
            dict(unit) | {"line": line}, story_title=title, siblings=siblings
        ),
        "event_intention": story.get("purpose") or "",
        "line": line,
        "story_episode": story["key"],
        "story_role": WEIGHT_ROLE[story["weight"]],
        "story_weight": story["weight"],
        "depicted_moment": f"source:{unit['asset_id']}",
        "moment_alternatives": [],
    }
