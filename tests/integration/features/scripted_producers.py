"""The model producers of a Basic preparation, answering from the fixture library (child side).

`scripted_preparation.py` installs these in the child `generate` in place of the producers that
run the pinned ONNX exports. Each takes the real producer's keyword arguments, is asked for the
sources the real preparation demands, and banks its rows through the same `HeadFactStore`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from immich_memories.analysis.editorial_clip_frames import clip_frames_fact
from immich_memories.analysis.editorial_obstruction import CLEAR_LABEL, HEAD_NAME, HEAD_VERSION
from immich_memories.analysis.editorial_preparation_detectors import (
    DETECTOR_VERSIONS,
    MARQO_HEAD,
)
from immich_memories.cache.embedding_cache import HeadFactStore
from immich_memories.triage.heads import HeadFact
from tests.e2e.fake_library import ALL_PICTURES, HELD_PICTURES, Picture

# Banked as its own producer, so no row here can pass for one a real export decided.
_ENCODER_KEY = "scripted-feature-producer"
_PICTURES: dict[str, Picture] = {p.asset_id: p for p in (*ALL_PICTURES, *HELD_PICTURES)}
# A Live Photo's clip shows what its still shows.
_STILL_OF_CLIP: dict[str, Picture] = {
    p.live_video_id: p for p in (*ALL_PICTURES, *HELD_PICTURES) if p.live_video_id
}


def _people(picture: Picture | None) -> str:
    """The people head's answer: how many faces Immich holds on the picture."""
    faces = len(picture.faces or picture.people) if picture else 0
    if faces == 0:
        return "none"
    return {1: "one", 2: "two"}.get(faces, "small-group" if faces <= 5 else "crowd")


def _clean_public(picture: Picture | None) -> dict[str, str]:
    people = _people(picture)
    return {
        "people": people,
        "children": "undetermined",
        "location": "outdoor",
        "activity": "other",
        "venue": "other",
        "frame_kind": "place_or_scenery" if people == "none" else "people_moment",
        "screen": "no",
        "uncovered_person": "no",
    }


class _Producers:
    def __init__(self, overrides: Mapping[str, Mapping[str, str]], log: str | None) -> None:
        self._overrides = overrides
        self._log = Path(log) if log else None

    def answer(self, asset_id: str, head: str) -> str:
        if head in self._overrides.get(asset_id, {}):
            return self._overrides[asset_id][head]
        picture = _PICTURES.get(asset_id) or _STILL_OF_CLIP.get(asset_id)
        if head == MARQO_HEAD:
            return "no"
        if head == "doc_docling":
            return "photograph"
        return _clean_public(picture).get(head, "undetermined")

    def note(self, producer: str, ids: Sequence[str]) -> None:
        if self._log is not None:
            with self._log.open("a") as out:
                out.write(json.dumps({"producer": producer, "ids": sorted(ids)}) + "\n")

    def bank(self, store: Any, rows: Mapping[str, Mapping[str, str]]) -> None:
        facts = {
            asset_id: [
                HeadFact(head=head, label=self.answer(asset_id, head), confidence=0.9, version=v)
                for head, v in heads.items()
            ]
            for asset_id, heads in rows.items()
        }
        HeadFactStore(store).remember_facts(facts, encoder_key=_ENCODER_KEY)

    def heads(self, *, asset_ids, store, head_versions, progress, **_real: Any) -> None:
        self.note("public_heads", asset_ids)
        self.bank(store, {asset_id: dict(head_versions) for asset_id in asset_ids})
        progress("public_heads", len(asset_ids), len(asset_ids))

    def detectors(self, *, pending, store, **_real: Any) -> dict[str, str]:
        rows: dict[str, dict[str, str]] = {}
        for head, ids in pending.items():
            self.note(f"detector:{head}", ids)
            for asset_id in ids:
                rows.setdefault(asset_id, {})[head] = DETECTOR_VERSIONS[head]
        self.bank(store, rows)
        return {}

    def clip_frames(self, *, frame_paths, store, **_real: Any) -> dict[str, str]:
        self.note("clip_frames", list(frame_paths))
        facts = {
            asset_id: [fact]
            for asset_id in frame_paths
            if (
                fact := clip_frames_fact(
                    [self.answer(asset_id, "frame_kind")] * len(frame_paths[asset_id])
                )
            )
        }
        HeadFactStore(store).remember_facts(facts, encoder_key=_ENCODER_KEY)
        return {}

    def obstruction(self, *, asset_ids, store, **_real: Any) -> dict[str, str]:
        self.note("obstruction", asset_ids)
        facts = {
            asset_id: [
                HeadFact(head=HEAD_NAME, label=CLEAR_LABEL, confidence=0.1, version=HEAD_VERSION)
            ]
            for asset_id in asset_ids
        }
        HeadFactStore(store).remember_facts(facts, encoder_key=_ENCODER_KEY)
        return {}

    def obstruction_frames(self, *, frame_paths, **_real: Any) -> dict[str, str]:
        # A video never measured for obstruction plays as it did before the head existed.
        self.note("obstruction_frames", list(frame_paths))
        return {}


def scripted_ports(
    overrides: Mapping[str, Mapping[str, str]], log: str | None
) -> dict[str, Callable[..., Any]]:
    """`PreparationPorts` fields for every producer that needs an ONNX export."""
    producers = _Producers(overrides, log)
    return {
        "heads": producers.heads,
        "detectors": producers.detectors,
        "clip_frames": producers.clip_frames,
        "obstruction": producers.obstruction,
        "obstruction_frames": producers.obstruction_frames,
    }
