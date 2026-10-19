"""A run of captures where most of them are flagged holds the whole run to the family.

The exposure head decides one picture at a time, and a nappy change or a bath is not one
picture: it is three minutes of them, of which the head catches some and misses the rest.
Those missed ones sit between two holds and are the same scene.

The window is the capture spacing the selector already uses -- an asset joins the run of
the one before it when it was taken within five minutes of it
(``MIN_GAP_IN_CAPTURE_GROUP_SECONDS``). A run is swept only when at least half of it is
flagged and at least three of its captures are. Both bounds are the owner's: half keeps a
run that is mostly ordinary from being swept by a corner of it, and three is what stops one
breastfeeding picture -- or two -- from holding minutes of family pictures around it. One
or two hits therefore hold only themselves, which is what ``exposure_evidence`` already did.

Measured on the owner's library at 5 minutes / 50 % / 3 flagged: normal months moved from
2.6 % to 2.8 % held, baby months from 18.5 % to 21.0 %, and 319 clean captures out of
66,597 were swept in. A fifteen-minute window added nothing.

The rules tier holds every carrier to the family anyway, so what this changes is the
model tier's verdicts and what a ``shareable`` export may carry.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from operator import itemgetter
from typing import Any

from immich_memories.analysis.audience.questions import exposure_flagged
from immich_memories.analysis.corpus.moment_grouping import MIN_GAP_IN_CAPTURE_GROUP_SECONDS
from immich_memories.api.models import Asset

WINDOW_SECONDS = MIN_GAP_IN_CAPTURE_GROUP_SECONDS
MIN_FLAGGED_SHARE = 0.5
# One breastfeeding picture must not hold the minutes of family pictures around it, and
# neither must two. Three flagged captures in one five-minute run is a scene, not a corner.
MIN_FLAGGED = 3
POLICY = (
    f"exposure-chain-v1-{WINDOW_SECONDS}s-{int(MIN_FLAGGED_SHARE * 100)}pc-{MIN_FLAGGED}flagged"
)


@dataclass(frozen=True, slots=True)
class ChainHold:
    """The run one held capture belongs to, and why the run was swept."""

    size: int
    flagged: int
    swept_in: bool

    def as_evidence(self) -> dict[str, object]:
        return {
            "policy": POLICY,
            "chain_size": self.size,
            "chain_flagged": self.flagged,
            "window_seconds": WINDOW_SECONDS,
            "swept_in": self.swept_in,
        }


def held_chains(rows: Iterable[tuple[str, datetime, bool]]) -> dict[str, ChainHold]:
    """Every capture a flagged run holds, keyed by id, with the run it belongs to.

    ``rows`` are ``(asset_id, taken, flagged)``; order does not matter. A capture in no
    swept run is absent, flagged or not: this only ever adds holds.
    """
    ordered: list[tuple[str, datetime, bool]] = sorted(rows, key=itemgetter(1, 0))
    held: dict[str, ChainHold] = {}
    for chain in _chains(ordered):
        flagged = sum(1 for row in chain if row[2])
        if flagged < MIN_FLAGGED or flagged < len(chain) * MIN_FLAGGED_SHARE:
            continue
        for asset_id, _taken, was_flagged in chain:
            held[asset_id] = ChainHold(len(chain), flagged, swept_in=not was_flagged)
    return held


def runs_holding(rows: Iterable[tuple[str, datetime]], asset_ids: Collection[str]) -> set[str]:
    """Every capture in a run that holds one of these ids, the ids included.

    ``rows`` are ``(asset_id, taken)``, the same clock ``held_chains`` runs on. Whether a run
    holds one of its pictures is decided by all of the run's flags, so a film preparing that
    picture prepares its run: an unread neighbour would count as a clean capture and could
    only ever lift a hold.
    """
    ordered = sorted(((asset_id, taken, False) for asset_id, taken in rows), key=itemgetter(1, 0))
    return {
        row[0]
        for chain in _chains(ordered)
        if any(row[0] in asset_ids for row in chain)
        for row in chain
    }


def _chains(
    ordered: Sequence[tuple[str, datetime, bool]],
) -> list[list[tuple[str, datetime, bool]]]:
    chains: list[list[tuple[str, datetime, bool]]] = []
    for row in ordered:
        if chains and (row[1] - chains[-1][-1][1]).total_seconds() <= WINDOW_SECONDS:
            chains[-1].append(row)
        else:
            chains.append([row])
    return chains


def chain_holds_for(
    assets: Mapping[str, Asset],
    annotations: Mapping[str, Any],
    clip_heads: Mapping[str, Mapping[str, str]],
) -> dict[str, ChainHold]:
    """The same answer from the film's own sources and their annotation lines.

    The clock is the one the selector orders carriers by, and the flag is the one
    ``exposure_flagged`` already reads: no second opinion about either. A Live Photo is one
    capture: its clip is not a run member of its own (it has no line, so it would only
    dilute the run as a clean capture), and a flagged clip flags its still.
    """
    return held_chains(
        (
            asset_id,
            asset.file_created_at,
            _flagged(annotations.get(asset_id))
            or exposure_flagged(dict(clip_heads.get(str(asset.live_photo_video_id or ""), {}))),
        )
        for asset_id, asset in assets.items()
    )


def _flagged(line: Any) -> bool:
    return line is not None and exposure_flagged(dict(line.heads))


class ExposureChains(dict[str, ChainHold]):
    """The period's holds, kept current for the runs a preparation round touches.

    A round prepares a handful of pictures, and only the runs they sit in can change: a hold
    is decided by the flags of its own run. Recomputing every run of the period for each
    round costs more the longer the period, so this keeps the period sorted once and
    re-derives just the runs around the pictures that were prepared. Like ``chain_holds_for``
    it only ever adds holds.
    """

    def __init__(
        self,
        assets: Mapping[str, Asset],
        annotations: Mapping[str, Any],
        clip_heads: Mapping[str, Mapping[str, str]],
    ) -> None:
        super().__init__(chain_holds_for(assets, annotations, clip_heads))
        self._assets = assets
        self._annotations = annotations
        self._clip_heads = clip_heads
        self._order = sorted(
            (asset.file_created_at, asset_id) for asset_id, asset in assets.items()
        )
        self._still_of_clip = {
            str(asset.live_photo_video_id): asset_id
            for asset_id, asset in assets.items()
            if asset.live_photo_video_id
        }

    def refresh(self, prepared_ids: Iterable[str]) -> None:
        """Re-derive the runs holding these pictures (or the stills of these clips)."""
        runs: list[tuple[int, int]] = []
        for asset_id in {self._still_of_clip.get(i, i) for i in prepared_ids}:
            asset = self._assets.get(asset_id)
            if asset is None:
                continue
            at = bisect_left(self._order, (asset.file_created_at, asset_id))
            low, high = at, at
            while low > 0 and self._gap(low - 1, low) <= WINDOW_SECONDS:
                low -= 1
            while high + 1 < len(self._order) and self._gap(high, high + 1) <= WINDOW_SECONDS:
                high += 1
            runs.append((low, high))
        for low, high in set(runs):
            self.update(
                held_chains(
                    (
                        asset_id,
                        taken,
                        _flagged(self._annotations.get(asset_id))
                        or exposure_flagged(
                            dict(
                                self._clip_heads.get(
                                    str(self._assets[asset_id].live_photo_video_id or ""), {}
                                )
                            )
                        ),
                    )
                    for taken, asset_id in self._order[low : high + 1]
                )
            )

    def _gap(self, before: int, after: int) -> float:
        return (self._order[after][0] - self._order[before][0]).total_seconds()
