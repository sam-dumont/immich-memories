"""Private, typed source metadata for reproducing a planning attempt.

This captures the DTOs actually read, including Live companion metadata. A full
offline replay still needs immutable annotation, people and thumbnail evidence.
The wall-sources-v1 codec is shared with the existing sealed matrix adapter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from immich_memories.analysis.exact_copies import FoldedPool
from immich_memories.analysis.selection_source import SourceScope
from immich_memories.analysis.source_filter import asset_id_of, asset_of
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.api.person_expression import PersonExpression
from immich_memories.security import write_secret_file

FORMAT = "wall-sources-v1"
SNAPSHOT_VERSION = "editorial-source-snapshot-v1"
SNAPSHOT_NAME = "source-snapshot.private.json"


def source_payload(
    sources: Sequence[Asset | VideoClipInfo], *, person_expression: PersonExpression | None = None
) -> dict[str, Any]:
    """Retain complete DTO fields, clip wrappers and input order without changing them."""
    rows = [
        {
            "kind": "clip" if isinstance(source, VideoClipInfo) else "asset",
            "value": source.model_dump(mode="json"),
        }
        for source in sources
    ]
    payload: dict[str, Any] = {"format": FORMAT, "count": len(rows), "sources": rows}
    if person_expression is not None:
        payload["person_expression"] = person_expression.to_dict()
    return payload


def sources_from_payload(payload: Mapping[str, Any]) -> tuple[Asset | VideoClipInfo, ...]:
    """Read legacy sealed walls and verify content identity when a snapshot supplies it."""
    if payload.get("format") != FORMAT:
        raise ValueError(f"unexpected wall sources format {payload.get('format')!r}")
    if "content_sha256" in payload:
        content = {key: value for key, value in payload.items() if key != "content_sha256"}
        if payload["content_sha256"] != _digest(content):
            raise ValueError("source snapshot content SHA256 does not match")
    sources = []
    for row in payload["sources"]:
        if row["kind"] not in {"clip", "asset"}:
            raise ValueError(f"unexpected source kind {row['kind']!r}")
        model = VideoClipInfo if row["kind"] == "clip" else Asset
        sources.append(model.model_validate(row["value"]))
    if payload.get("count") != len(sources):
        raise ValueError("source snapshot count does not match its DTOs")
    return tuple(sources)


def load_sources(path: Path) -> tuple[Asset | VideoClipInfo, ...]:
    return sources_from_payload(json.loads(Path(path).read_text()))


def frozen_access(attempt_dir: Path) -> dict[str, str]:
    """The account each of an attempt's pictures was read through, as its snapshot froze it.

    Each source's owner account, then each exact-copy group's kept copy over it: a replay
    reads the copy the attempt chose, through the account that chose it. Empty for an
    attempt that read one account or kept no snapshot.
    """
    path = Path(attempt_dir) / SNAPSHOT_NAME
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    access = {
        asset.id: asset.access_accounts[0]
        for asset in map(asset_of, sources_from_payload(payload))
        if asset.access_accounts
    }
    for group in payload.get("exact_copies", ()):
        if group["access_account"] is not None:
            access[group["representative_id"]] = group["access_account"]
    return access


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported source snapshot value: {type(value).__name__}")


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(payload).encode()).hexdigest()


class AttemptSourceSnapshots:
    """Write once per attempt, even when the source-fetch closure is reused."""

    def __init__(self) -> None:
        self._written: set[Path] = set()
        self._lock = Lock()

    def capture(
        self,
        sources: Sequence[Asset | VideoClipInfo],
        *,
        directory: Path,
        scope: SourceScope,
        person_expression: PersonExpression | None = None,
        people: tuple[str, ...] = (),
        person_match: str = "and",
        owner_excluded_asset_ids: tuple[str, ...] = (),
    ) -> None:
        path = Path(directory).resolve() / SNAPSHOT_NAME
        with self._lock:
            if path in self._written:
                return
            payload = source_payload(sources, person_expression=person_expression)
            assets = [
                source.asset if isinstance(source, VideoClipInfo) else source for source in sources
            ]
            linked = {asset.live_photo_video_id for asset in assets if asset.live_photo_video_id}
            captured = {asset.id for asset in assets if asset.id in linked and asset.is_video}
            payload.update(
                snapshot_version=SNAPSHOT_VERSION,
                requested_scope=asdict(scope),
                people=list(people),
                person_match=person_match,
                owner_excluded_asset_ids=list(owner_excluded_asset_ids),
                linked_companion_count=len(linked),
                captured_companion_count=len(captured),
                missing_companion_ids=sorted(linked - captured),
            )
            payload["content_sha256"] = _digest(payload)
            write_secret_file(path, _json(payload))
            self._written.add(path)

    def freeze_copies(self, folded: FoldedPool, *, directory: Path) -> None:
        """Add the copy each exact-copy group kept, and the account it reads through.

        A replay then renders that copy even if a star moved since. A pool without
        copies leaves the snapshot as it was written.
        """
        path = Path(directory).resolve() / SNAPSHOT_NAME
        if not folded.groups or not path.exists():
            return
        accounts = {asset_id_of(source): asset_of(source).access_accounts for source in folded.pool}
        with self._lock:
            payload = json.loads(path.read_text())
            payload.pop("content_sha256", None)
            payload["exact_copies"] = [
                {
                    "content_key": group.content_key,
                    "representative_id": group.representative_id,
                    "access_account": next(iter(accounts.get(group.representative_id, ())), None),
                    "references": [asdict(reference) for reference in group.references],
                }
                for group in folded.groups
            ]
            payload["content_sha256"] = _digest(payload)
            write_secret_file(path, _json(payload))
