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
