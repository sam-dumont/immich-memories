"""Measure speech on a cut's carriers once, and bank it per picture for the next cut."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.api.access_clients import AccountReadFailed
from immich_memories.api.models import Asset
from immich_memories.db import Store
from immich_memories.processing.probe_cache import ProbeCache, ProbeError
from immich_memories.speech.fireredvad import FireRedSpeechDetector
from immich_memories.speech.vad import VAD_SAMPLE_RATE, extract_audio_16k
from immich_memories.store.cut_measurements import (
    PendingMeasurements,
    banked_speech_facts,
    banked_speech_regions,
)

logger = logging.getLogger(__name__)

# v2: #1951 banks a music fraction beside the regions; a v1 row never answered it.
METHOD = "firered-aed-utterances-v2"

Regions = list[tuple[float, float]]


def speech_producer(config: Any) -> str:
    """The detector and the exact settings behind an answer, composed into its bank key."""
    settings = json.dumps(config.model_dump(), sort_keys=True, separators=(",", ":"))
    return f"speech-regions-v1@{METHOD}/{hashlib.sha256(settings.encode()).hexdigest()[:12]}"


def read_speech_regions(
    store: Store, assets: Iterable[Asset], producer: str
) -> dict[str, tuple[tuple[float, float], ...]]:
    """The speech a cut already measured in these clips, keyed by clip."""
    digests = {asset.id: source_metadata_digest(asset) for asset in assets}
    if not digests:
        return {}
    return banked_speech_regions(store, digests, producer)


class SpeechMeasurementUnavailable(RuntimeError):
    """A selected source could not be measured for speech.

    Speech-boundary protection is a best-effort refinement on top of an already
    valid cut: a playback, download or audio-extraction failure means that one
    carrier keeps its selected interval, not that the memory is unrenderable.
    """


class SpeechFacts:
    """Only retained motion pays for audio extraction; what it measures is banked per clip."""

    def __init__(
        self,
        *,
        assets: Mapping[str, Asset],
        store: Store,
        fetch,
        config,
        measure: Callable[[str], tuple[Regions, float]] | None = None,
    ):
        self.assets, self.store, self.fetch = assets, store, fetch
        self.detector = FireRedSpeechDetector(config.vad_threshold, config.min_silence_ms)
        self.producer = speech_producer(config)
        self.memo: dict[tuple[str, str], Regions] = {}
        self.music_memo: dict[tuple[str, str], float] = {}
        self._measure_source = measure or self._measure
        self._banked: dict[str, tuple[tuple[tuple[float, float], ...], float]] | None = None
        self._pending = PendingMeasurements(store)

    def __call__(self, asset_id: str) -> Regions:
        digest = source_metadata_digest(self.assets[asset_id])
        if (asset_id, digest) in self.memo:
            return self.memo[(asset_id, digest)]
        if self._banked is None:
            # Every clip this cut could ask about, regions and music fraction together,
            # read off the bank once (#1951).
            digests = {a.id: source_metadata_digest(a) for a in self.assets.values()}
            self._banked = banked_speech_facts(self.store, digests, self.producer)
        if asset_id in self._banked:
            banked_regions, music_fraction = self._banked[asset_id]
            regions = list(banked_regions)
        else:
            regions, music_fraction = self._measure_source(asset_id)
            self._remember(asset_id, digest, regions, music_fraction)
        self.memo[(asset_id, digest)] = regions
        self.music_memo[(asset_id, digest)] = music_fraction
        return regions

    def music_for(self, asset_id: str) -> float:
        """The music/singing share this cut measured in a clip, or 0.0 when unmeasured."""
        digest = source_metadata_digest(self.assets[asset_id])
        return self.music_memo.get((asset_id, digest), 0.0)

    def flush(self) -> None:
        """Bank what this cut measured and has not written yet."""
        try:
            self._pending.flush()
        except SQLAlchemyError as error:
            # An unwritable bank costs the next cut a measurement, never this cut.
            logger.debug("Speech regions were not banked: %s", type(error).__name__)

    def _remember(
        self, asset_id: str, digest: str, regions: Regions, music_fraction: float
    ) -> None:
        try:
            self._pending.speech_regions(
                asset_id=asset_id,
                producer=self.producer,
                source_digest=digest,
                regions=regions,
                music_fraction=music_fraction,
            )
        except SQLAlchemyError as error:
            logger.debug(
                "Speech regions for %s were not banked: %s", asset_id, type(error).__name__
            )

    def _measure(self, asset_id: str) -> tuple[Regions, float]:
        with tempfile.TemporaryDirectory(prefix="editorial-speech-") as directory:
            path = Path(directory) / "source.mp4"
            try:
                self.fetch(asset_id, path)
            except AccountReadFailed:
                raise
            except Exception as error:
                # WHY: any transport failure is "this source cannot be measured",
                # which degrades the refinement; only a caller seeing this class
                # may treat it as non-fatal.
                raise SpeechMeasurementUnavailable(
                    f"playback for {asset_id} could not be fetched: {type(error).__name__}"
                ) from error
            if not path.exists() or not path.stat().st_size:
                raise SpeechMeasurementUnavailable(f"playback for {asset_id} was empty")
            try:
                probe = ProbeCache().get(path)
            except ProbeError as error:
                raise SpeechMeasurementUnavailable(
                    f"playback for {asset_id} could not be probed: {type(error).__name__}"
                ) from error
            if not probe.has_audio:
                return [], 0.0
            audio = extract_audio_16k(path)
            if audio is None:
                raise SpeechMeasurementUnavailable(
                    f"audio for {asset_id} could not be extracted for speech detection"
                )
            regions, music_fraction = self.detector.detect_with_music(audio, VAD_SAMPLE_RATE)
            return [(r.start, r.end) for r in regions], music_fraction
