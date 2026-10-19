"""Remote readings of sampled frames, banked only after a complete clip answer."""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from immich_memories.analysis.facts.clip_frames import clip_frames_fact
from immich_memories.analysis.facts.obstruction import HEAD_NAME as OBSTRUCTION_HEAD
from immich_memories.analysis.facts.obstruction import HEAD_VERSION as OBSTRUCTION_VERSION
from immich_memories.analysis.facts.obstruction import OBSTRUCTED_LABEL
from immich_memories.analysis.preparation.detectors import MARQO_HEAD, MARQO_VERSION
from immich_memories.analysis.preparation.obstruction_bank import bank_obstructed_seconds
from immich_memories.analysis.preparation.remote_facts import (
    FactsAnswer,
    RemoteFactsClient,
    RemoteFactsError,
)
from immich_memories.api.models import Asset
from immich_memories.cache.embedding_cache import HeadFactStore, PendingHeadFacts
from immich_memories.config.models.inference import InferenceConfig
from immich_memories.db import Store
from immich_memories.store.cut_measurements import PendingMeasurements
from immich_memories.triage.heads import HeadFact


def prepare_remote_frame_facts(
    *,
    exposure: Sequence[str],
    clips: Mapping[str, Sequence[Path]],
    frame_paths: Mapping[str, Sequence[Path]],
    preview_paths: Mapping[str, Path],
    store: Store,
    config: InferenceConfig,
    check: Callable[[], None],
    progress: Callable[[str, int, int], None] | None = None,
    obstruction: Mapping[str, Asset] | None = None,
) -> float | None:
    """Read frames once for every model, retaining preview exposure but excluding its kind.

    ``obstruction`` names the videos whose sampled frames also owe their obstructed
    seconds; each frame upload is asked that alongside the rest. No partial clip is
    banked. Completed clips survive a later request failure, and endpoint or execution
    provider never changes their model identity.
    """
    obstruction = obstruction or {}
    charged: list[float] = []
    asset_ids = tuple(dict.fromkeys((*exposure, *clips, *obstruction)))
    report = progress or (lambda _stage, _done, _total: None)
    report("remote_frames", 0, len(asset_ids))
    with (
        RemoteFactsClient(config) as remote,
        PendingHeadFacts(HeadFactStore(store)) as bank,
        PendingMeasurements(store) as measured,
    ):
        for index, asset_id in enumerate(asset_ids, 1):
            wanted = _Wanted(asset_id in exposure, asset_id in clips, asset_id in obstruction)
            answers, frame_answers = _read_clip(
                remote,
                frame_paths.get(asset_id, ()),
                preview_paths.get(asset_id) if wanted.exposure else None,
                wanted,
                concurrency=config.facts_concurrency,
                check=check,
            )
            rows = _aggregate(answers, frame_answers, exposure=wanted.exposure, kinds=wanted.kinds)
            check()
            for key, fact in rows:
                bank.add(asset_id, [fact], encoder_key=key)
            if wanted.obstruction:
                bank_obstructed_seconds(measured, obstruction[asset_id], _flagged(frame_answers))
            # A completed clip must be durable before a watcher counts it.
            bank.flush()
            measured.flush()
            report("remote_frames", index, len(asset_ids))
            charged.extend(a.service_seconds for a in answers if a.service_seconds is not None)
    return sum(charged) if charged else None


@dataclass(frozen=True)
class _Wanted:
    exposure: bool
    kinds: bool
    obstruction: bool

    def frame_versions(self) -> dict[str, str]:
        versions = {}
        if self.exposure:
            versions[MARQO_HEAD] = MARQO_VERSION
        if self.kinds:
            versions["frame_kind"] = "public-v1"
        if self.obstruction:
            versions[OBSTRUCTION_HEAD] = OBSTRUCTION_VERSION
        return versions


def _read_clip(remote, paths, preview, wanted, *, concurrency, check):
    versions = wanted.frame_versions()
    requests = [(path.read_bytes(), versions) for path in paths]
    if preview is not None:
        requests.append((preview.read_bytes(), {MARQO_HEAD: MARQO_VERSION}))
    check()
    # At most one clip's eight frames and preview are queued. Every model shares
    # each frame upload; the configured window also bounds simultaneous requests.
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="frame-facts") as pool:
        answers = []
        for answer in pool.map(remote.facts, (r[0] for r in requests), (r[1] for r in requests)):
            check()
            answers.append(answer)
    return answers, answers[: len(paths)]


def _flagged(frame_answers: Sequence[FactsAnswer]) -> list[bool]:
    _key, facts = _facts(frame_answers, OBSTRUCTION_HEAD, OBSTRUCTION_HEAD)
    if len(facts) != len(frame_answers):
        raise RemoteFactsError("Remote frame classifiers omitted a frame's obstruction answer")
    return [fact.label == OBSTRUCTED_LABEL for fact in facts]


def _aggregate(answers, frame_answers, *, exposure, kinds):
    rows = []
    if exposure:
        key, facts = _facts(answers, MARQO_HEAD, MARQO_HEAD)
        rows.append((key, max(facts, key=lambda fact: fact.confidence)))
    if kinds:
        key, facts = _facts(frame_answers, "heads", "frame_kind")
        if fact := clip_frames_fact([fact.label for fact in facts]):
            rows.append((key, fact))
    return rows


def _facts(answers: Sequence[FactsAnswer], producer: str, head: str) -> tuple[str, list[HeadFact]]:
    keys = {answer.producers[producer].encoder_key for answer in answers}
    if len(keys) != 1:
        raise RemoteFactsError(
            "Remote frame classifiers returned missing or inconsistent model identities"
        )
    facts = [
        fact
        for answer in answers
        for fact in answer.producers[producer].bank_facts()
        if fact.head == head
    ]
    return keys.pop(), facts
