"""Read the caption origins a run saved, and say how many distinct ones it found."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

# The two sentinel groups `store.caption_provenance` folds assets into.
_UNKNOWN = "unknown"
_NONE = "none"


def _describe(origin: Mapping[str, object]) -> str:
    served = ", ".join(
        f"{key}={value}" for key, value in sorted(_mapping(origin.get("served")).items())
    )
    digest = str(origin.get("control_digest") or "")
    return "; ".join(
        [
            str(origin.get("model_id", "unknown model")),
            str(origin.get("endpoint", "unknown endpoint")),
            str(origin.get("artifact_id") or "artifact not declared"),
            served or "build not reported",
            f"controls {digest}" if digest else "controls not measured",
        ]
    )


def _unknown(origin: Mapping[str, object]) -> str:
    contract = origin.get("contract")
    return f"unknown, banked before origins were recorded ({contract})" if contract else _UNKNOWN


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _origins(provenance: object) -> list[dict]:
    rows = _mapping(provenance).get("origins")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def caption_origin_summary(provenance: object) -> str:
    """One line naming every distinct captioner behind a run's captions, or nothing.

    The count is the point: a bank filled by two servers that word `setting`
    differently is the failure #933 names, and until something counts the origins
    nobody sees the seam. The line is printed, so `setup_matrix_capture` can read
    it off stdout with the rest of the preparation table.
    """
    origins = [row for row in _origins(provenance) if row.get("status") != _NONE]
    if not origins:
        return ""
    captions = sum(int(row.get("assets", 0)) for row in origins)
    labels = "; ".join(
        f"{_unknown(row) if row.get('status') == _UNKNOWN else _describe(row)} x{row.get('assets', 0)}"
        for row in origins
    )
    mixed = " MIXED" if len(origins) > 1 else ""
    return f"caption origins: {len(origins)} distinct over {captions} captions{mixed} [{labels}]"


def _record(path: Path) -> dict[str, object]:
    try:
        return _mapping(json.loads(path.read_text()))
    except (OSError, ValueError):
        return {}


def _preparations(attempt: Path) -> Iterator[tuple[Path, dict[str, object]]]:
    paths = [attempt / "preparation.private.json"]
    paths.extend(sorted((attempt / "refinement").glob("*/preparation.private.json")))
    for path in paths:
        if record := _record(path):
            yield path.parent, record


def _origin(record: Mapping[str, object], asset_id: str) -> dict | None:
    provenance = _mapping(record.get("caption_provenance"))
    origins = _origins(provenance)
    by_asset = _mapping(provenance.get("by_asset"))
    requested = record.get("requested_asset_ids")
    if isinstance(requested, list) and asset_id not in requested:
        return None
    if not origins:
        return None
    index = by_asset.get(asset_id, 0)
    return origins[index] if type(index) is int and 0 <= index < len(origins) else origins[0]


def read_captions(attempt: Path, asset_ids: Sequence[str]) -> dict[str, str]:
    """Captions the saved run read, including every refinement round.

    An empty value means the run recorded a caption read but predates text snapshots.
    Never consult the live annotation bank: its captions may have changed since the cut.
    """
    captions: dict[str, str] = {}
    for directory, record in _preparations(attempt):
        saved = _record(directory / "captions.private.json")
        for asset in asset_ids:
            origin = _origin(record, asset)
            if origin is not None and origin.get("status") != _NONE:
                captions.setdefault(asset, "")
            if isinstance(text := saved.get(asset), str) and text:
                captions[asset] = text
    return captions


def caption_origin_note(attempt: Path, asset_id: str) -> str:
    """What produced a picture's caption, from its own saved refinement or initial pass."""
    records = [record for _, record in _preparations(attempt)]
    for record in reversed(records):
        origin = _origin(record, asset_id)
        if origin is None:
            continue
        if origin.get("status") == _NONE:
            return ""
        if origin.get("status") == _UNKNOWN:
            written_under = f"; written as {origin['contract']}" if origin.get("contract") else ""
            return f"Caption origin: unknown (not recorded with this caption{written_under})"
        return "Caption origin: " + _describe(origin)
    if any(isinstance(record.get("caption_provenance"), Mapping) for record in records):
        return ""
    return "Caption origin: unknown (not recorded for this run)"
