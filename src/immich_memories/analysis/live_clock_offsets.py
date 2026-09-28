"""Live companion clock offsets, measured once per pair of companions and banked.

Measuring a join downloads both companions and decodes them with ffprobe and ffmpeg. A
year holds over a thousand companions, so the answer is kept like a motion residual: per
pair, per producer, per exact source metadata. A second cut over the same Live Photos
downloads nothing, and a refused join is an answer too.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence

import httpx
import numpy as np
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset
from immich_memories.db import Store
from immich_memories.processing.stitch_alignment import (
    OFFSET_METHOD,
    CompanionUndecodable,
    companion_frames,
    pairwise_clock_offset,
)
from immich_memories.store.cut_measurements import (
    PendingMeasurements,
    measured_clock_offsets,
)

logger = logging.getLogger(__name__)

OFFSET_PRODUCER = f"live-clock-offset-v1@{OFFSET_METHOD}"

Pair = tuple[str, str]


class _Unavailable(Exception):
    """This run could not fetch a companion; the next run may, so nothing is banked."""


class BankedClockOffsets:
    """The clock-offset probe a cut measures kept bursts with (see `ClockOffsetProbe`).

    Each companion of a burst is downloaded and decoded at most once per call, and the
    call's answers are banked together as it returns, so an interrupted cut keeps its work.
    """

    def __init__(
        self,
        *,
        store: Store | None,
        companions: Mapping[str, Asset],
        fetch: Callable[[str], bytes],
        frames: Callable[[bytes], np.ndarray] = companion_frames,
    ) -> None:
        self.store = store
        self.companions = companions
        self.fetch = fetch
        self.frames = frames
        self.memo: dict[Pair, float | None] = {}
        self.metrics = {"banked_pairs": 0, "measured_pairs": 0, "downloads": 0}
        self._measured: dict[Pair, tuple[str, float | None]] | None = None

    def __call__(self, video_ids: Sequence[str]) -> list[float | None]:
        pairs = list(zip(video_ids, video_ids[1:], strict=False))
        self._read_bank([pair for pair in pairs if pair not in self.memo])
        decoded: dict[str, np.ndarray | None] = {}
        measured: dict[Pair, float | None] = {}
        try:
            for pair in pairs:
                if pair not in self.memo:
                    self._measure(pair, decoded, measured)
        finally:
            self._remember(measured)
        return [self.memo.get(pair) for pair in pairs]

    def _digest(self, pair: Pair) -> str | None:
        companions = [self.companions.get(video_id) for video_id in pair]
        if any(companion is None for companion in companions):
            return None
        joined = "|".join(source_metadata_digest(c) for c in companions if c is not None)
        return hashlib.sha256(joined.encode()).hexdigest()

    def _read_bank(self, pairs: list[Pair]) -> None:
        if self.store is None or not pairs:
            return
        if self._measured is None:
            self._measured = measured_clock_offsets(self.store, OFFSET_PRODUCER)
        banked = {
            pair: seconds
            for pair in pairs
            if (row := self._measured.get(pair)) is not None
            for digest, seconds in (row,)
            if digest == self._digest(pair)
        }
        self.memo.update(banked)
        self.metrics["banked_pairs"] += len(banked)

    def _decoded(self, video_id: str, decoded: dict[str, np.ndarray | None]) -> np.ndarray | None:
        if video_id not in decoded:
            try:
                payload = self.fetch(video_id)
            except (OSError, httpx.HTTPError, ImmichAPIError) as error:
                raise _Unavailable(type(error).__name__) from error
            self.metrics["downloads"] += 1
            try:
                decoded[video_id] = self.frames(payload)
            except CompanionUndecodable:
                decoded[video_id] = None
            except OSError as error:
                raise _Unavailable(type(error).__name__) from error
        return decoded[video_id]

    def _measure(
        self,
        pair: Pair,
        decoded: dict[str, np.ndarray | None],
        measured_now: dict[Pair, float | None],
    ) -> None:
        try:
            first, second = (self._decoded(video_id, decoded) for video_id in pair)
        except _Unavailable:
            # One unreachable companion leaves its joins unstitched in this cut only.
            self.memo[pair] = None
            return
        measured = (
            pairwise_clock_offset(first, second)
            if first is not None and second is not None
            else None
        )
        self.memo[pair] = measured.seconds if measured is not None else None
        self.metrics["measured_pairs"] += 1
        measured_now[pair] = self.memo[pair]

    def _remember(self, measured: Mapping[Pair, float | None]) -> None:
        if self.store is None or not measured:
            return
        try:
            with PendingMeasurements(self.store, size=len(measured) + 1) as pending:
                for pair, seconds in measured.items():
                    if (digest := self._digest(pair)) is not None:
                        pending.clock_offset(
                            pair=pair,
                            producer=OFFSET_PRODUCER,
                            source_digest=digest,
                            seconds=seconds,
                        )
        except SQLAlchemyError as error:
            # An unwritable bank costs the next cut a measurement, never this cut.
            logger.debug("Clock offsets were not banked: %s", type(error).__name__)
