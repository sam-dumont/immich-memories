"""The preview every preparation stage reads: fetched once, verified, and cached."""

from __future__ import annotations

import io
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from PIL import Image

PREVIEW_UNAVAILABLE = "preview unavailable at Immich (HTTP 404)"


def preview_refused(exc: BaseException) -> bool:
    """Whether Immich answered about this source, rather than failing to answer at all.

    The client has already spent its retries by the time either arrives here: a
    404 is never retried and a timeout is raised only after the last attempt. So
    a 404 is the server's settled answer -- it has no preview for this asset and
    a rerun will not change that -- while everything else is unfinished work.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 404


def ensure_preview(path: Path, asset_id: str, fetch_preview) -> None:
    """Keep a verified preview at `path`, fetching it only when the cached one is unusable.

    The payload is verified as a picture before it replaces anything, and written
    atomically, so a half-written or corrupt download never becomes the cached preview.
    """
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError):
        pass
    else:
        # Reuse is use. The cache evicts oldest mtime first, so without this a
        # preview an earlier run downloaded still looks as old as that run while
        # this one reads it back for pixels, heads, sheets and the caption --
        # and a preview that vanishes between those stages is recorded as a
        # missing fact rather than fetched again.
        with suppress(OSError):
            os.utime(path)
        return
    payload = fetch_preview(asset_id) if fetch_preview else None
    if not payload:
        raise FileNotFoundError(
            "Immich preview missing or corrupt; provide fetch_preview or populate the configured thumbnail cache"
        )
    with Image.open(io.BytesIO(payload)) as image:
        image.verify()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
