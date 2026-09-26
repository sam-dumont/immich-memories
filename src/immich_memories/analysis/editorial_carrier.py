"""A picture's own story context, shared by draft selection and every later insertion."""

from collections.abc import Mapping
from typing import Any

from immich_memories.analysis.editorial_story_replies import WEIGHT_ROLE


def carrier_row(
    unit: Mapping[str, Any],
    *,
    family: str,
    anchor: str,
    story: Mapping[str, Any],
    chapter: int,
    line: str,
) -> dict[str, Any]:
    """Bind playable facts to their own story, never the outgoing picture's story."""
    return dict(unit) | {
        "event": family,
        "anchor": anchor,
        "chapter": chapter,
        "why": f"{story.get('title', '')}: {line[:80]}",
        "event_intention": story.get("purpose") or "",
        "line": line,
        "story_episode": story["key"],
        "story_role": WEIGHT_ROLE[story["weight"]],
        "story_weight": story["weight"],
        "depicted_moment": f"source:{unit['asset_id']}",
        "moment_alternatives": [],
    }
