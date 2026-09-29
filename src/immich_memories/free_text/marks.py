"""The owner's verdict on a free-text film: pictures marked wrong, and what is missing.

A report of a bad result says where it went wrong. A picture marked wrong gets the stage that
admitted it and whether the engine picked it; a missing thing is checked word by word against
the translation: did the reading keep the word, was it offered as a subject word, picked as
the subject, and does any pool picture's caption say it?
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from immich_memories.free_text.linking import GLUE
from immich_memories.free_text.reading import words_of

_PRINTED = "printed text"


def marked(
    record: Mapping[str, Any],
    *,
    wrong: Sequence[str] = (),
    missing: str = "",
    pool_captions: Iterable[str | None] = (),
) -> dict[str, Any]:
    """The run's free-text record with the owner's marks added to those it already holds.

    `record` is what `save_with_run` kept; `pool_captions` are the pool pictures' captions.
    """
    basis = record.get("marks_basis", {})
    flagged = [*record.get("flagged", [])]
    seen = {row["asset_id"] for row in flagged}
    flagged += [
        _flag(asset_id, record, basis) for asset_id in dict.fromkeys(wrong) if asset_id not in seen
    ]
    result = {**record, "flagged": flagged}
    if missing:
        result |= {
            "missing": missing,
            "missing_check": _check(missing, record, basis, pool_captions),
        }
    return result


def _flag(asset_id: str, record: Mapping[str, Any], basis: Mapping[str, Any]) -> dict[str, str]:
    if asset_id not in basis.get("pool", ()):
        return {"asset_id": asset_id, "stage": "not from the pool", "verdict": "not in the pool"}
    admitted = basis.get("admitted", {})
    printed = asset_id in basis.get("anchors", ())
    stage = _PRINTED if printed else admitted.get("stage", "pool")
    picked = asset_id in record.get("picks", ())
    return {
        "asset_id": asset_id,
        "stage": stage,
        "verdict": "picked by the engine" if picked else "in the pool, not picked",
        # The rule that kept it; quoted words make it caption-like, so it shares that opt-in.
        "reason": "OCR read the requested words on it" if printed else admitted.get("reason", ""),
    }


def _check(
    missing: str,
    record: Mapping[str, Any],
    basis: Mapping[str, Any],
    pool_captions: Iterable[str | None],
) -> dict[str, list[str]]:
    words = [word for word in dict.fromkeys(words_of(missing)) if word not in GLUE]
    spec = record.get("spec", {})
    offered = {row["word"] for row in spec.get("words", [])}
    picked = {row["word"] for field in ("subject", "alongside") for row in spec.get(field, [])}
    said = {word for caption in pool_captions if caption for word in words_of(caption)}
    read = set(basis.get("read", ()))
    return {
        "offered": [word for word in words if word in offered],
        "picked": [word for word in words if word in picked],
        "in_pool": [word for word in words if word in said],
        "read": [word for word in words if word in read],
    }
