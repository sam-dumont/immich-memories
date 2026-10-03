"""What a kept clip shows and says, measured once, after the selection, at a fixed cost (#1949).

The picture comes from the playback's MP4 index: how much each half second changes, read
off the size of its predicted frames, with nothing decoded. The sound comes from the audio
of one bounded span, fetched by byte range: its loudness every half second and the speech
the detector hears in it. A clip up to a minute is heard whole; a longer one for a minute
around its picture's peak, so a five-minute clip costs what a one-minute one does.

Measured on the NAS (Celeron J4125) over the owner's library: 0.7-2.5 s a clip, once.
"""

from __future__ import annotations

import hashlib
import logging
import struct
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.analysis.editorial_video_windows import choose_window
from immich_memories.api.access_clients import AccountReadFailed
from immich_memories.api.models import Asset
from immich_memories.db import Store
from immich_memories.processing.playback_keyframes import AUDIO_RATE, PlaybackIndex
from immich_memories.store.cut_measurements import PendingMeasurements, banked_motion_residuals

logger = logging.getLogger(__name__)

# A minute of sound: a birthday's cheer came 27 s into a 63 s clip, after the singing.
LISTEN_SECONDS = 60.0
LOUDNESS_BIN_SECONDS = 0.5
METHOD = "index-frame-sizes+loudness+speech-v2"


class SpeechDetector(Protocol):
    @property
    def available(self) -> bool: ...

    def detect(self, audio: Any, sample_rate: int) -> list: ...


@dataclass(frozen=True)
class WindowFacts:
    """(second, activity) of the picture; the speech and (second, dB) loudness heard over
    ``heard``, all on the clip's clock."""

    activity: tuple[tuple[float, float], ...]
    speech: tuple[tuple[float, float], ...]
    heard: tuple[float, float] | None
    loudness: tuple[tuple[float, float], ...] = ()


def facts_producer(detector_settings: str) -> str:
    digest = hashlib.sha256(detector_settings.encode()).hexdigest()[:12]
    return f"window-facts-v1@{METHOD}/{digest}"


class ClipWindowFacts:
    """Each kept video's window facts, measured once per source and banked for every later cut.

    ``read(asset_id, start, length)`` answers a byte range of the playback with its full
    size. A playback whose index cannot be read answers None and keeps its opening.
    """

    def __init__(
        self,
        *,
        assets: Mapping[str, Asset],
        store: Store,
        read: Callable[[str, int, int], tuple[bytes, int]],
        detector: SpeechDetector | None,
        detector_settings: str = "",
    ) -> None:
        self._assets, self._store, self._read = assets, store, read
        self._detector = detector if detector is not None and detector.available else None
        self._producer = facts_producer(detector_settings if self._detector else "no-speech")
        self._banked: dict[str, dict] | None = None
        self._known: dict[str, WindowFacts] = {}
        self._pending = PendingMeasurements(store)

    def __call__(self, asset_id: str, hold: float) -> WindowFacts | None:
        if asset_id not in self._known:
            facts = self._from_bank(asset_id) or self._measure(asset_id, hold)
            if facts is None:
                return None
            self._known[asset_id] = facts
        return self._known[asset_id]

    def speech_for(self, asset_id: str) -> list[tuple[float, float]] | None:
        """The speech this cut heard in a clip, or None when it listened to none of it."""
        facts = self._known.get(asset_id)
        if facts is None or facts.heard is None:
            return None
        return list(facts.speech)

    def flush(self) -> None:
        """Bank what this cut measured and has not written yet."""
        try:
            self._pending.flush()
        except SQLAlchemyError as error:
            logger.debug("Window facts were not banked: %s", type(error).__name__)

    def _from_bank(self, asset_id: str) -> WindowFacts | None:
        if self._banked is None:
            digests = {a.id: source_metadata_digest(a) for a in self._assets.values()}
            self._banked = banked_motion_residuals(self._store, digests, self._producer)
        row = self._banked.get(asset_id)
        if row is None:
            return None
        heard = row.get("heard")
        return WindowFacts(
            tuple((float(t), float(v)) for t, v in row["activity"]),
            tuple((float(a), float(b)) for a, b in row["speech"]),
            (float(heard[0]), float(heard[1])) if heard else None,
            tuple((float(t), float(db)) for t, db in row.get("loudness", [])),
        )

    def _measure(self, asset_id: str, hold: float) -> WindowFacts | None:
        try:
            with tempfile.TemporaryDirectory(prefix="editorial-window-") as directory:
                facts = self._listen(asset_id, hold, Path(directory))
        except AccountReadFailed:
            raise
        except (httpx.HTTPError, OSError, ValueError, struct.error) as error:
            # WHY: the window refines a valid cut; a clip whose playback cannot be read
            # plays its opening, as every clip did before.
            logger.warning("Could not read %s for its window: %s", asset_id, error)
            return None
        self._pending.motion_residual(
            asset_id=asset_id,
            producer=self._producer,
            source_digest=source_metadata_digest(self._assets[asset_id]),
            measured={
                "activity": [list(row) for row in facts.activity],
                "speech": [list(row) for row in facts.speech],
                "heard": list(facts.heard) if facts.heard else None,
                "loudness": [list(row) for row in facts.loudness],
            },
        )
        return facts

    def _listen(self, asset_id: str, hold: float, workdir: Path) -> WindowFacts:
        index = PlaybackIndex(lambda start, length: self._read(asset_id, start, length))
        activity = index.activity()
        duration = index.duration
        if duration <= LISTEN_SECONDS:
            heard = (0.0, duration)
        else:
            seen = choose_window(activity, duration=duration, hold=hold)
            first = min(max(0.0, seen + hold / 2 - LISTEN_SECONDS / 2), duration - LISTEN_SECONDS)
            heard = (first, first + LISTEN_SECONDS)
        pcm = index.audio(*heard, workdir=workdir)
        if pcm is None:
            return WindowFacts(activity, (), None)
        loudness = _loudness(pcm, offset=heard[0])
        if self._detector is None:
            return WindowFacts(activity, (), None, loudness)
        speech = tuple(
            (round(heard[0] + r.start, 3), round(heard[0] + r.end, 3))
            for r in self._detector.detect(pcm, AUDIO_RATE)
        )
        return WindowFacts(activity, speech, heard, loudness)


def _loudness(pcm: np.ndarray, *, offset: float) -> tuple[tuple[float, float], ...]:
    width = int(AUDIO_RATE * LOUDNESS_BIN_SECONDS)
    return tuple(
        (
            round(offset + i / AUDIO_RATE, 3),
            round(float(20 * np.log10(np.sqrt(np.mean(pcm[i : i + width] ** 2)) + 1e-9)), 1),
        )
        for i in range(0, len(pcm) - width + 1, width)
    )
