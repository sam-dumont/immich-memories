"""The exact inputs a cut's render used, kept beside its plan so a later render reuses them.

A finished cut's clips carry what the pipeline certified while choosing them (a Live Photo's
manifest, a source's measured duration). Rebuilding those later would mean re-running the
projection or quietly rendering a Live Photo as a still. So the cut writes them once, and a
revision renders from the same objects with only its own edits on top.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import VideoClipInfo
from immich_memories.security import write_secret_file

RENDER_INPUTS_FILE = "render-inputs.private.json"
_FORMAT = "editorial-render-inputs-v1"


@dataclass(frozen=True)
class RenderInputs:
    clips: tuple[VideoClipInfo, ...]
    selections: tuple[EditorialSelection, ...]
    segments: dict[str, tuple[float, float]]
    binding: dict[str, Any]


def write_render_inputs(
    attempt_dir: Path,
    clips: Sequence[VideoClipInfo],
    selections: Sequence[EditorialSelection],
    segments: Mapping[str, tuple[float, float]],
    binding: Mapping[str, Any],
) -> None:
    """Keep what the render of this cut will read, private like the rest of the attempt."""
    record = {
        "format": _FORMAT,
        "clips": [clip.model_dump(mode="json", by_alias=True) for clip in clips],
        "selections": [asdict(selection) for selection in selections],
        "segments": {key: list(value) for key, value in segments.items()},
        "binding": dict(binding),
    }
    write_secret_file(Path(attempt_dir) / RENDER_INPUTS_FILE, json.dumps(record, indent=2))


def read_render_inputs(attempt_dir: Path) -> RenderInputs | None:
    """The render inputs this cut kept, or None for a cut made before they were kept."""
    path = Path(attempt_dir) / RENDER_INPUTS_FILE
    if not path.is_file():
        return None
    record = json.loads(path.read_text())
    if record.get("format") != _FORMAT:
        return None
    return RenderInputs(
        clips=tuple(VideoClipInfo.model_validate(row) for row in record["clips"]),
        selections=tuple(EditorialSelection(**row) for row in record["selections"]),
        segments={key: (float(a), float(b)) for key, (a, b) in record["segments"].items()},
        binding=record["binding"],
    )


CUT_TITLES_FILE = "cut-titles.private.json"


@dataclass(frozen=True)
class CutTitles:
    """What `generate` decided about the film's title and memory when it made the cut."""

    title: str | None
    subtitle: str | None
    source: str | None
    preset_params: dict[str, Any]


def _encode(value: Any) -> Any:
    # Dates are tagged so they come back as dates: a trip's title counts its days from them.
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Mapping):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        if set(value) == {"__date__"}:
            return date.fromisoformat(value["__date__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def write_cut_titles(
    attempt_dir: Path,
    *,
    title: str | None,
    subtitle: str | None,
    source: Any,
    preset_params: Mapping[str, Any],
) -> None:
    """Keep the title the cut was given and its memory parameters, for a render made later."""
    record = {
        "title": title,
        "subtitle": subtitle,
        "source": getattr(source, "value", source),
        "preset_params": _encode(dict(preset_params)),
    }
    write_secret_file(Path(attempt_dir) / CUT_TITLES_FILE, json.dumps(record, indent=2))


def read_cut_titles(attempt_dir: Path) -> CutTitles | None:
    """The cut's titles, or None for a cut made before they were kept."""
    try:
        record = json.loads((Path(attempt_dir) / CUT_TITLES_FILE).read_text())
    except (OSError, ValueError):
        return None
    return CutTitles(
        title=record.get("title"),
        subtitle=record.get("subtitle"),
        source=record.get("source"),
        preset_params=_decode(record.get("preset_params") or {}),
    )
