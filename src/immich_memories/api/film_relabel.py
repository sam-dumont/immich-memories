"""Give a film already in Immich its label again, without rendering it again (#2627).

The upload writes a film's description and tags once Immich has read it. When the label was lost
(a slow read took it back) or the label format changed, this writes the current label to the
asset a run was delivered as, by the same write-and-settle path, and removes the app's own tags
the current label no longer has. A tag outside the app's label kinds is never touched.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from immich_memories.api.album_service import (
    DESCRIBE,
    AlbumService,
    RequestFn,
    UploadWaits,
    tag_rights_missing,
)
from immich_memories.api.film_label import FilmLabel, is_label_tag
from immich_memories.api.generated_asset_tags import GENERATED_MEMORY_TAG
from immich_memories.api.permissions import ApiKeyCapabilities

logger = logging.getLogger(__name__)

# A removal Immich took back is removed again; each pass also rewrites the label.
_PASSES = 2


class RelabelStatus(StrEnum):
    WRITTEN = "written"
    UNCHANGED = "unchanged"
    ASSET_GONE = "asset_gone"
    RIGHTS_MISSING = "rights_missing"
    FAILED = "failed"


@dataclass(frozen=True)
class RelabelOutcome:
    """What a re-label did to one asset. `detail` names the missing rights; `removed` the stale
    tags taken off; `warnings` what did not stay."""

    status: RelabelStatus
    detail: str = ""
    removed: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class FilmRelabeler:
    """Re-apply a film's label to its asset: check it exists and the key's rights, write,
    settle, read back, and take off the app's own tags the label no longer has."""

    def __init__(
        self,
        albums: AlbumService,
        request_fn: RequestFn,
        key_capabilities_fn: Callable[[], Awaitable[ApiKeyCapabilities]],
    ) -> None:
        self._albums = albums
        self._request = request_fn
        self._capabilities = key_capabilities_fn

    async def relabel(
        self, asset_id: str, label: FilmLabel, *, waits: UploadWaits
    ) -> RelabelOutcome:
        """Write `label` to the asset, or say why it was not written."""
        allows = (await self._capabilities()).allows
        lacking = tag_rights_missing(allows)
        if label.description and not allows(DESCRIBE):
            lacking.append(DESCRIBE)
        if lacking:
            return RelabelOutcome(
                RelabelStatus.RIGHTS_MISSING, "the key lacks " + ", ".join(lacking)
            )
        try:
            asset = await self._request("GET", f"/assets/{asset_id}") or {}
        except Exception as exc:  # WHY: any client's 404 carries a status; the rest is raised
            if getattr(exc, "status_code", None) == 404:
                return RelabelOutcome(RelabelStatus.ASSET_GONE)
            raise
        wanted = (GENERATED_MEMORY_TAG, *label.tags)
        if not _stale(asset, wanted) and not _label_differs(asset, label, wanted):
            return RelabelOutcome(RelabelStatus.UNCHANGED)
        return await self._write(asset_id, asset, label, wanted, waits)

    async def _write(
        self,
        asset_id: str,
        asset: dict[str, Any],
        label: FilmLabel,
        wanted: tuple[str, ...],
        waits: UploadWaits,
    ) -> RelabelOutcome:
        written = FilmLabel(label.description, wanted)
        removed: list[str] = []
        not_kept: list[str] = []
        stale = _stale(asset, wanted)
        for _ in range(_PASSES):
            for tag_id, value in stale:
                # One tag per call, each settled: Immich rewrites the sidecar per write.
                await self._request("DELETE", f"/tags/{tag_id}/assets", json={"ids": [asset_id]})
                await self._albums.settled(asset_id, waits.quiet_polls)
                removed.append(value)
            not_kept = await self._albums.apply_label_once_read(
                asset_id, written, waits=waits, already_read=True
            )
            asset = await self._request("GET", f"/assets/{asset_id}") or {}
            stale = _stale(asset, wanted)
            if not stale and not not_kept:
                break
        warnings = [f"the film's {name} did not stay" for name in not_kept]
        warnings += [f"{value} did not stay removed" for _, value in stale]
        gone = tuple(dict.fromkeys(v for v in removed if v not in {s for _, s in stale}))
        return RelabelOutcome(RelabelStatus.WRITTEN, removed=gone, warnings=tuple(warnings))


def _stale(asset: dict[str, Any], wanted: tuple[str, ...]) -> list[tuple[str, str]]:
    """The (id, value) of the app's own label tags on the asset that the label no longer has."""
    return [
        (str(tag["id"]), str(tag["value"]))
        for tag in asset.get("tags") or ()
        if isinstance(tag, dict)
        and tag.get("id")
        and is_label_tag(str(tag.get("value") or ""))
        and tag["value"] not in wanted
    ]


def _label_differs(asset: dict[str, Any], label: FilmLabel, wanted: tuple[str, ...]) -> bool:
    kept = str((asset.get("exifInfo") or {}).get("description") or "").strip()
    carried = {t.get("value") for t in asset.get("tags") or () if isinstance(t, dict)}
    return (bool(label.description) and kept != label.description) or not set(wanted) <= carried
