"""Whether a unit plays as motion, and what kind of source the reader is told it is."""

import math
from collections.abc import Mapping
from typing import Any, cast

from immich_memories.analysis.clips.budget import RESIDUAL_MIN
from immich_memories.analysis.judgments.json_numbers import exact_number

MOVING_KINDS = frozenset({"video", "live-motion"})


def carries_motion(unit: Mapping[str, Any]) -> bool:
    """Does this unit play? A true video always does; a Live Photo only above the discriminant."""
    return str(unit.get("kind") or "") in MOVING_KINDS


def measured_motion(unit: Mapping[str, Any]) -> bool:
    """Is this unit's motion a measured fact rather than a hope?

    A Live Photo counts only once its companion measured at or above the discriminant: a
    Live Photo nobody measured yet plans as motion, but nothing says anything happens in it.
    A true video is held to the same bar once its sampled frames were measured (#1166); one
    nobody measured still counts by what it is, as every video did before it could be.
    """
    kind = str(unit.get("kind") or "")
    residual = exact_number(unit.get("residual"))
    if kind == "video":
        return residual is None or residual >= RESIDUAL_MIN
    return kind == "live-motion" and residual is not None and residual >= RESIDUAL_MIN


def source_kind_marker(unit: Mapping[str, Any]) -> str:
    """What the reader is offered: a video with its true source length, a Live Photo whose motion
    plays, or one that will be shown as a still.

    A proposed carrier length is not the duration of its original recording.
    """
    kind = str(unit.get("kind") or "")
    if kind == "video":
        for key in ("raw_seconds", "source_seconds", "duration"):
            value = unit.get(key)
            # An exact int/float only: a bool or a numeric string is not a measured duration.
            if type(value) in (int, float):
                seconds = cast(float, value)
                if math.isfinite(seconds) and seconds > 0:
                    return f" | video {seconds:g} s source"
        return " | video (source duration unknown)"
    if not kind.startswith("live"):
        return ""
    return (
        " | live photo, motion plays" if carries_motion(unit) else " | live photo, shown as a still"
    )
