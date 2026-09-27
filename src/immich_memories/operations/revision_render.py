"""What a cut, or one of its revisions, renders: the cut's own inputs with the owner's edits.

Both the CLI and the web client render through here and then through `generate_memory`, so a
revision never takes a different road to the film than the cut it came from.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from immich_memories.operations.cut_revisions import CutRevision
from immich_memories.operations.storyboard import moment_alternatives
from immich_memories.processing.editorial_owner_edits import (
    EditorialOwnerEditProjection,
    project_editorial_owner_edits,
)
from immich_memories.processing.render_inputs import read_render_inputs

if TYPE_CHECKING:
    from immich_memories.api.models import VideoClipInfo
    from immich_memories.processing.editorial_timing import EditorialTimingPolicy

ClipFetcher = Callable[[str], "VideoClipInfo | None"]


class RenderUnavailable(RuntimeError):
    """This cut cannot be rendered again as it stands; the message says what to do."""


def project_revision(
    attempt_dir: Path,
    revision: CutRevision | None,
    fetch_clip: ClipFetcher,
    policy: EditorialTimingPolicy | None,
) -> EditorialOwnerEditProjection:
    """The clips, directives, segments and timeline to render for this cut or revision.

    `fetch_clip` loads a swapped-in sibling from Immich; nothing else is fetched, because the
    cut's own clips come back exactly as its first render used them.
    """
    inputs = read_render_inputs(Path(attempt_dir))
    if inputs is None or policy is None:
        raise RenderUnavailable(
            "This cut was made before a cut kept its render inputs. Cut again to render it."
        )
    edits = revision.edits if revision else None
    replacements = {}
    for original, sibling in (edits.swaps if edits else {}).items():
        clip = fetch_clip(sibling)
        if clip is None:
            raise RenderUnavailable(f"{sibling} is no longer in the library")
        replacements[original] = clip
    removed = set(edits.removed) if edits else set()
    return project_editorial_owner_edits(
        original_clips=inputs.clips,
        original_selections=inputs.selections,
        original_binding=inputs.binding,
        selected_ids=[clip.asset.id for clip in inputs.clips if clip.asset.id not in removed],
        requested_segments={**inputs.segments, **(dict(edits.segments) if edits else {})},
        policy=policy,
        replacements=replacements,
        moment_siblings=moment_alternatives(Path(attempt_dir)),
    )
