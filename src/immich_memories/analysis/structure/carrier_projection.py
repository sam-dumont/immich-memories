"""Whether a carrier row can render from its source media, asked before the film finalizes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, Literal

from immich_memories.api.models import AssetType

if TYPE_CHECKING:
    from immich_memories.analysis.film.contract import StructurePlanningInput


CARRIER_KINDS = frozenset({"still", "live-still", "live-motion", "video"})


def _seconds(value: object, name: str, *, zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"editorial {name} must be numeric")
    number = float(value)
    if not isfinite(number) or number < 0 or (number == 0 and not zero):
        raise ValueError(f"editorial {name} must be finite and positive")
    return number


@dataclass(frozen=True)
class Carrier:
    """One native carrier row after its own numbers were checked against each other."""

    asset_id: str
    kind: str
    seconds: float
    start: float
    end: float
    frame: float | None

    @property
    def mode(self) -> Literal["motion", "still"]:
        return "motion" if self.kind in {"live-motion", "video"} else "still"


def carrier_from(row: dict) -> Carrier:
    kind = row["kind"]
    if kind not in CARRIER_KINDS:
        raise ValueError("unknown editorial carrier rendering kind")
    seconds = _seconds(row["seconds"], "carrier duration")
    start = _seconds(row.get("start_time", 0.0), "source start", zero=True)
    end = _seconds(row.get("end_time", start + seconds), "source end")
    if abs(end - start - seconds) > 1e-6:
        raise ValueError("editorial source interval disagrees with carrier duration")
    frame = row.get("render_frame_seconds")
    if frame is not None:
        frame = _seconds(frame, "source frame", zero=True)
    return Carrier(row["asset_id"], kind, seconds, start, end, frame)


def projection_problem(
    row: Mapping[str, Any], asset_type: AssetType, *, include_live_photos: bool
) -> str | None:
    """Why this carrier cannot render from its source, or None when projection accepts it.

    The same question ``_projected_clip`` enforces, asked before the film finalizes: a
    carrier that fails it retires in the planner instead of dying at the render with every
    model call already spent.
    """
    carrier = carrier_from(dict(row))
    if carrier.kind == "live-motion":
        if not include_live_photos or asset_type != AssetType.IMAGE:
            return "editorial Live motion is outside the requested media contract"
        return None
    if asset_type == AssetType.VIDEO:
        if carrier.kind != "video" and carrier.frame is None:
            return "editorial video still requires an exact source frame"
        return None
    if asset_type == AssetType.IMAGE and carrier.mode == "still":
        if carrier.start != 0 or carrier.frame is not None:
            return "editorial photograph cannot claim video source timing"
        return None
    return "editorial carrier kind disagrees with source media"


def retire_unprojectable(
    carriers: list[dict], source: StructurePlanningInput, cut_carriers: list[dict]
) -> list[dict]:
    """Drop the carriers the strict projection refuses, retiring them into ``cut_carriers``.

    The projection question asked before membership and timing finalize, so hours of model
    work never die at the render: the gates upstream have already had their chance to
    substitute, and the film may simply shrink here. A retired row carries its ``reason``
    and ``review_stage``.
    """
    kept: list[dict] = []
    for carrier in carriers:
        asset = source.assets.get(carrier["asset_id"])
        problem = (
            projection_problem(carrier, asset.type, include_live_photos=source.allow_live_motion)
            if asset is not None
            else "editorial carrier has no captured source"
        )
        if problem is None:
            kept.append(carrier)
        else:
            cut_carriers.append(
                carrier | {"reason": problem, "review_stage": "projection-finalize"}
            )
    return kept
