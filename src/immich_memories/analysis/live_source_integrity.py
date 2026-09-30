"""Retained Live originals are playable only under a byte-bound presentation proof."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from os import stat_result
from pathlib import Path
from typing import Protocol

from immich_memories.analysis.editorial_structure_contract import StructurePlanningInput
from immich_memories.processing.probe_cache import ProbeError, VideoProbe


class PresentationProbe(Protocol):
    def get(self, path: Path) -> VideoProbe: ...

    def decoder_identity(self) -> str: ...

    def complete_video_presentation(self, path: Path) -> dict: ...


class OriginalSourceIntegrity:
    """Persist valid and media-invalid answers; infrastructure failures remain failures."""

    def __init__(
        self,
        *,
        fetch: Callable[[str], Path],
        directory: Path,
        probes: PresentationProbe,
        policy: str,
    ) -> None:
        self.fetch = fetch
        self.directory = directory
        self.probes = probes
        self.policy = policy

    def __call__(self, video_ids: Sequence[str]) -> Mapping[str, dict]:
        return {
            video_id: self._proof(self.fetch(video_id)) for video_id in dict.fromkeys(video_ids)
        }

    def _proof(self, path: Path) -> dict:
        initial = path.stat()
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        identity = {
            "source_sha256": digest,
            "video_stream_index": self.probes.get(path).video_stream_index,
            "decoder_identity": self.probes.decoder_identity(),
            "presentation_policy": self.policy,
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        record = self.directory / f"{key}.json"
        cached = self._cached(record, identity)
        if cached is not None:
            self._unchanged(path, initial)
            return cached
        proof = self._checked(path)
        self._unchanged(path, initial)
        if any(proof.get(key) != value for key, value in identity.items()):
            raise ValueError("Original presentation proof changed its source or decoder identity")
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as temporary:
            json.dump(proof, temporary, sort_keys=True)
            staged = Path(temporary.name)
        staged.replace(record)
        return proof

    @staticmethod
    def _unchanged(path: Path, initial: stat_result) -> None:
        current = path.stat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(current, name) != getattr(initial, name) for name in fields):
            raise ValueError("Original Live source changed during presentation verification")

    @staticmethod
    def _cached(record: Path, identity: dict) -> dict | None:
        if not record.is_file():
            return None
        try:
            proof = json.loads(record.read_text())
        except (ValueError, OSError):
            return None
        if (
            isinstance(proof, dict)
            and isinstance(proof.get("valid"), bool)
            and all(proof.get(key) == value for key, value in identity.items())
        ):
            return proof
        return None

    def _checked(self, path: Path) -> dict:
        try:
            return self.probes.complete_video_presentation(path) | {"valid": True}
        except ProbeError as error:
            from immich_memories.processing.probe_cache import PresentationIntegrityError

            if not isinstance(error, PresentationIntegrityError):
                raise
            return dict(error.evidence) | {"valid": False, "reason": error.reason}


def production_live_source_integrity(
    source: StructurePlanningInput, *, resources: ExitStack
) -> OriginalSourceIntegrity | None:
    """Read originals only for retained motion; existing cache/download rules still apply."""
    from immich_memories.analysis.editorial_runtime_ports import _stage_reads
    from immich_memories.cache.video_cache import VideoDownloadCache
    from immich_memories.processing.probe_cache import PRESENTATION_POLICY, ProbeCache

    if not source.allow_live_motion:
        return None
    config = source.config.cache
    directory = config.video_cache_path
    if not config.video_cache_enabled:
        temporary = resources.enter_context(tempfile.TemporaryDirectory(prefix="live-originals-"))
        directory = Path(temporary)
    cache = VideoDownloadCache(
        directory,
        max_size_gb=config.video_cache_max_size_gb,
        max_age_days=config.video_cache_max_age_days,
    )
    batch = resources.enter_context(cache.begin_batch())
    client = None

    def fetch(video_id: str) -> Path:
        nonlocal client
        if client is None:
            client = _stage_reads(source)
            resources.callback(client.close)
        path = batch.download_video_id(client, video_id)
        if path is None:
            raise RuntimeError("Original Live companion unavailable; no integrity verdict recorded")
        return path

    return OriginalSourceIntegrity(
        fetch=fetch,
        directory=config.cache_path / "structure-banks" / "live-source-integrity",
        probes=ProbeCache(),
        policy=PRESENTATION_POLICY,
    )
