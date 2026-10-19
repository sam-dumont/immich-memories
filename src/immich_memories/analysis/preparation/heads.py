"""The heads that read the pinned DINOv2 encoder, decided off one encoder call per picture.

The eight public context heads read the pooled pack, the obstruction head the patch tokens
the pack discards, and a preview's scene print is the pack itself. One preview (or one
clip's sampled frames) is decoded and encoded once, and each reader banks only what that
picture still owes it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import UnidentifiedImageError

from immich_memories.analysis.facts.clip_frames import clip_frames_fact
from immich_memories.analysis.preparation.obstruction_bank import (
    bank_obstructed_seconds,
    flagged_frames,
    obstruction_facts,
)
from immich_memories.analysis.preparation.scene_prints import PRINT_ENCODER_KEY, ScenePrintBank
from immich_memories.api.models import Asset
from immich_memories.cache.embedding_cache import HeadFactStore, PendingHeadFacts
from immich_memories.db import Store
from immich_memories.processing.memory_budget import available_cpus
from immich_memories.store.cut_measurements import PendingMeasurements
from immich_memories.triage.encoder import DinoEncoder
from immich_memories.triage.engine import BANK_PICTURES
from immich_memories.triage.heads import HeadBundle, PatchHeadBundle
from immich_memories.triage.preprocess import preprocess_image_bytes

PUBLIC_HEAD_VERSIONS = {
    "activity": "public-v1",
    "children": "public-v1",
    "location": "public-v1",
    "people": "public-v1",
    "venue": "oi-v3",
    # Distilled from a typed picture reader's answers on the same public corpus. The two
    # binary heads carry their operating band in their coefficients; `public-v1-strict`
    # says so in the version string, because the band is what makes `screen` add-only.
    "frame_kind": "public-v1",
    "screen": "public-v1-strict",
    "uncovered_person": "public-v1",
}

PUBLIC_STAGE = "public_heads"
OBSTRUCTION_STAGE = "obstruction"
CLIP_FRAMES_STAGE = "clip_frames"
OBSTRUCTION_FRAMES_STAGE = "obstruction_frames"
_UNREADABLE = (OSError, ValueError, UnidentifiedImageError)


def missing_encoder_message(encoder_path: Path) -> str:
    """The one sentence a missing encoder is reported with, in preflight and mid-run alike."""
    return (
        f"public heads need the pinned DINOv2 ONNX export at {encoder_path}. "
        "Run `immich-memories models fetch` to download it, or point "
        "advanced.triage.encoder at your copy of the export."
    )


@dataclass(frozen=True)
class _Readers:
    """What one encoder pass feeds, and which pictures each reader still owes."""

    encoder: DinoEncoder
    public: HeadBundle | None
    obstruction: PatchHeadBundle | None
    owes_public: frozenset[str]
    owes_obstruction: frozenset[str]

    def owes(self, asset_id: str) -> bool:
        return asset_id in self.owes_public or asset_id in self.owes_obstruction


def prepare_heads(
    *,
    asset_ids: Sequence[str],
    store: Store,
    bundle_path: Path,
    encoder_path: Path,
    head_versions: Mapping[str, str],
    preview_for: Callable[[str], bytes],
    batch_size: int,
    check_cancelled: Callable[[], None],
    progress: Callable[[str, int, int], None],
    provider: str = "auto",
    obstruction_ids: Sequence[str] = (),
    obstruction_bundle_path: Path | None = None,
    scene_prints: Path | None = None,
    open_encoder: Callable[..., DinoEncoder] = DinoEncoder.open,
) -> dict[str, str]:
    """Bank the public heads for ``asset_ids`` and the obstruction head for
    ``obstruction_ids``, off one encoder call per picture that owes either.

    Returns what could not be decided, keyed ``public_heads:<id>``,
    ``obstruction:<id>`` or ``obstruction`` (that head could not load, which never
    stops the public heads). ``scene_prints`` is the bank selection reads its scene
    prints from; every pack decided here is banked there too.
    """
    failures: dict[str, str] = {}
    public = _public_bundle(bundle_path, head_versions) if asset_ids else None
    patch = _patch_bundle(obstruction_bundle_path, failures, OBSTRUCTION_STAGE)
    patch = patch if obstruction_ids else None
    # Refuse silent optional-triage fallback: preparation requires these facts.
    if not encoder_path.is_file():
        raise FileNotFoundError(missing_encoder_message(encoder_path))
    check_cancelled()
    encoder = open_encoder(encoder_path, provider=provider)
    if public is not None and public.encoder_key != encoder.key:
        raise ValueError("head bundle was trained on another encoder")
    patch = _same_encoder(patch, encoder, failures, OBSTRUCTION_STAGE)
    facts = HeadFactStore(store)
    readers = _Readers(
        encoder=encoder,
        public=public,
        obstruction=patch,
        owes_public=_owing_public(facts, asset_ids, public),
        owes_obstruction=_owing(facts, obstruction_ids, patch),
    )
    order = [a for a in dict.fromkeys((*asset_ids, *obstruction_ids)) if readers.owes(a)]
    prints = scene_prints if encoder.key == PRINT_ENCODER_KEY else None
    with PendingHeadFacts(facts, size=BANK_PICTURES) as bank, _print_bank(prints) as banked:
        for start in range(0, len(order), batch_size):
            chunk = order[start : start + batch_size]
            read = _read_previews(chunk, preview_for, check_cancelled, readers, failures)
            if read:
                _decide_previews(readers, read, bank, banked)
            progress(PUBLIC_STAGE, start + len(chunk), len(order))
    return failures


def _public_bundle(bundle_path: Path, head_versions: Mapping[str, str]) -> HeadBundle:
    bundle = HeadBundle.load(bundle_path)
    supplied = {head.name: head.version for head in bundle.heads}
    if any(supplied.get(head) != version for head, version in head_versions.items()):
        raise ValueError(
            "configured head bundle does not contain the required public head versions"
        )
    return bundle


def _patch_bundle(
    path: Path | None, failures: dict[str, str], stage: str
) -> PatchHeadBundle | None:
    """The rank-only obstruction head; one that cannot load never takes the others down."""
    if path is None:
        return None
    try:
        return PatchHeadBundle.load(path)
    except (OSError, ValueError, KeyError) as exc:
        failures[stage] = f"{type(exc).__name__}: {exc}"
        return None


def _same_encoder(
    bundle: PatchHeadBundle | None, encoder: DinoEncoder, failures: dict[str, str], stage: str
) -> PatchHeadBundle | None:
    if bundle is not None and bundle.encoder_key != encoder.key:
        failures[stage] = "ValueError: obstruction head bundle was trained on another encoder"
        return None
    return bundle


def _owing_public(
    facts: HeadFactStore, asset_ids: Sequence[str], bundle: HeadBundle | None
) -> frozenset[str]:
    """Pictures missing a fact for at least one head version in the bundle."""
    if bundle is None:
        return frozenset()
    complete = set(asset_ids)
    for head in bundle.heads:
        complete &= set(facts.facts_for(asset_ids, head=head.name, version=head.version))
    return frozenset(asset_ids) - complete


def _owing(
    facts: HeadFactStore, asset_ids: Sequence[str], bundle: PatchHeadBundle | None
) -> frozenset[str]:
    if bundle is None:
        return frozenset()
    banked = facts.facts_for(asset_ids, head=bundle.name, version=bundle.version)
    return frozenset(asset_ids) - set(banked)


@contextmanager
def _print_bank(path: Path | None) -> Iterator[ScenePrintBank | None]:
    if path is None:
        yield None
        return
    bank = ScenePrintBank(path)
    try:
        yield bank
    finally:
        bank.close()


def _preprocess_workers() -> int:
    return max(1, min(4, available_cpus() - 1))


def _read_previews(
    chunk: Sequence[str],
    preview_for: Callable[[str], bytes],
    check_cancelled: Callable[[], None],
    readers: _Readers,
    failures: dict[str, str],
) -> list[tuple[str, bytes, np.ndarray]]:
    """Each readable preview with its pixels; previews decode beside one another."""
    payloads: list[tuple[str, bytes]] = []
    for asset_id in chunk:
        # A stop is honoured picture by picture; what was decided before it is banked.
        check_cancelled()
        try:
            payloads.append((asset_id, preview_for(asset_id)))
        except _UNREADABLE as exc:
            _unreadable(asset_id, exc, readers, failures)
    with ThreadPoolExecutor(_preprocess_workers(), thread_name_prefix="preprocess") as pool:
        decoded = list(pool.map(_decoded, (payload for _asset_id, payload in payloads)))
    read = []
    for (asset_id, payload), pixels in zip(payloads, decoded, strict=True):
        if isinstance(pixels, np.ndarray):
            read.append((asset_id, payload, pixels))
        else:
            _unreadable(asset_id, pixels, readers, failures)
    return read


def _decoded(payload: bytes) -> np.ndarray | Exception:
    try:
        return preprocess_image_bytes(payload)
    except _UNREADABLE as exc:
        return exc


def _unreadable(
    asset_id: str, exc: BaseException, readers: _Readers, failures: dict[str, str]
) -> None:
    reason = f"{type(exc).__name__}: {exc}"
    if asset_id in readers.owes_public:
        failures[f"{PUBLIC_STAGE}:{asset_id}"] = reason
    if asset_id in readers.owes_obstruction:
        failures[f"{OBSTRUCTION_STAGE}:{asset_id}"] = reason


def _decide_previews(
    readers: _Readers,
    read: Sequence[tuple[str, bytes, np.ndarray]],
    bank: PendingHeadFacts,
    prints: ScenePrintBank | None,
) -> None:
    pixels = np.stack([pixels for _asset_id, _payload, pixels in read])
    packs, patches = readers.encoder.embed_with_patches(pixels)
    ids = [asset_id for asset_id, _payload, _pixels in read]
    key = readers.encoder.key
    if readers.public is not None and (
        rows := [row for row, asset_id in enumerate(ids) if asset_id in readers.owes_public]
    ):
        decided = readers.public.decide(packs[rows])
        for at, row in enumerate(rows):
            facts = [decided[head.name][at] for head in readers.public.heads]
            bank.add(ids[row], facts, encoder_key=key)
    if readers.obstruction is not None and (
        rows := [row for row, asset_id in enumerate(ids) if asset_id in readers.owes_obstruction]
    ):
        facts = obstruction_facts(readers.obstruction, pixels[rows], patches[rows])
        for row, fact in zip(rows, facts, strict=True):
            bank.add(ids[row], [fact], encoder_key=key)
    if prints is not None:
        for (_asset_id, payload, _pixels), pack in zip(read, packs, strict=True):
            prints.add(payload, pack)
        prints.flush()


def prepare_clip_frames(
    *,
    frame_paths: Mapping[str, Sequence[Path]],
    store: Store,
    bundle_path: Path,
    encoder_path: Path,
    check_cancelled: Callable[[], None],
    progress: Callable[[str, int, int], None] | None = None,
    provider: str = "auto",
    obstruction: Mapping[str, Sequence[Path]] | None = None,
    videos: Mapping[str, Asset] | None = None,
    obstruction_bundle_path: Path | None = None,
    open_encoder: Callable[..., DinoEncoder] = DinoEncoder.open,
) -> dict[str, str]:
    """Bank each clip's `clip_frames` fact and each video's obstructed seconds off one
    encoder call over its sampled frames.

    ``frame_paths`` are the clips that owe their frame reading, ``obstruction`` the
    videos (described in ``videos``) that owe their obstructed seconds. Returns what
    could not be read, keyed ``clip_frames:<id>``, ``obstruction_frames:<id>`` or
    ``obstruction_frames``: a clip keeps the reading of its preview, which is all any
    clip had before, and a video never measured plays exactly as it did.
    """
    report = progress or (lambda *_args: None)
    failures: dict[str, str] = {}
    owed = obstruction or {}
    patch = _patch_bundle(obstruction_bundle_path, failures, OBSTRUCTION_FRAMES_STAGE)
    patch = patch if owed else None
    kinds = HeadBundle.load(bundle_path) if frame_paths else None
    for stage, owing in ((CLIP_FRAMES_STAGE, frame_paths), (OBSTRUCTION_FRAMES_STAGE, owed)):
        if owing:
            report(stage, 0, len(owing))
    encoder = open_encoder(encoder_path, provider=provider)
    if kinds is not None and kinds.encoder_key != encoder.key:
        raise ValueError("head bundle was trained on another encoder")
    patch = _same_encoder(patch, encoder, failures, OBSTRUCTION_FRAMES_STAGE)
    reader = _FrameReader(encoder, kinds, patch, frame_paths, owed if patch else {}, videos or {})
    with PendingHeadFacts(HeadFactStore(store)) as bank, PendingMeasurements(store) as measured:
        for asset_id in dict.fromkeys((*frame_paths, *reader.owes_obstruction)):
            check_cancelled()
            reader.read(asset_id, bank, measured, failures)
            # A completed clip is durable before a watcher counts it.
            bank.flush()
            measured.flush()
            reader.counted(asset_id, report)
    return failures


@dataclass
class _FrameReader:
    encoder: DinoEncoder
    kinds: HeadBundle | None
    obstruction: PatchHeadBundle | None
    owes_kinds: Mapping[str, Sequence[Path]]
    owes_obstruction: Mapping[str, Sequence[Path]]
    videos: Mapping[str, Asset]
    kinds_done: int = 0
    obstruction_done: int = 0

    def read(
        self,
        asset_id: str,
        bank: PendingHeadFacts,
        measured: PendingMeasurements,
        failures: dict[str, str],
    ) -> None:
        paths = self.owes_kinds.get(asset_id) or self.owes_obstruction[asset_id]
        try:
            pixels = np.stack([preprocess_image_bytes(Path(p).read_bytes()) for p in paths])
        except _UNREADABLE as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if asset_id in self.owes_kinds:
                failures[f"{CLIP_FRAMES_STAGE}:{asset_id}"] = reason
            if asset_id in self.owes_obstruction:
                failures[f"{OBSTRUCTION_FRAMES_STAGE}:{asset_id}"] = reason
            return
        packs, patches = self.encoder.embed_with_patches(pixels)
        if self.kinds is not None and asset_id in self.owes_kinds:
            frame_kinds = [fact.label for fact in self.kinds.decide(packs)["frame_kind"]]
            if fact := clip_frames_fact(frame_kinds):
                bank.add(asset_id, [fact], encoder_key=self.encoder.key)
        if self.obstruction is not None and asset_id in self.owes_obstruction:
            flagged = flagged_frames(self.obstruction, pixels, patches)
            bank_obstructed_seconds(measured, self.videos[asset_id], flagged)

    def counted(self, asset_id: str, report: Callable[[str, int, int], None]) -> None:
        if asset_id in self.owes_kinds:
            self.kinds_done += 1
            report(CLIP_FRAMES_STAGE, self.kinds_done, len(self.owes_kinds))
        if asset_id in self.owes_obstruction:
            self.obstruction_done += 1
            report(OBSTRUCTION_FRAMES_STAGE, self.obstruction_done, len(self.owes_obstruction))
