"""Remote readings of sampled frames, banked only after a complete clip answer."""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from immich_memories.analysis.editorial_clip_frames import clip_frames_fact
from immich_memories.analysis.editorial_preparation_detectors import MARQO_HEAD, MARQO_VERSION
from immich_memories.analysis.remote_facts import FactsAnswer, RemoteFactsClient, RemoteFactsError
from immich_memories.cache.embedding_cache import HeadFactStore, PendingHeadFacts
from immich_memories.config_models_inference import InferenceConfig
from immich_memories.db import Store
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
) -> float | None:
    """Read frames once for both models, retaining preview exposure but excluding its kind.

    No partial clip is banked. Completed clips survive a later request failure, and
    endpoint or execution provider never changes their model identity.
    """
    charged: list[float] = []
    asset_ids = tuple(dict.fromkeys((*exposure, *clips)))
    report = progress or (lambda _stage, _done, _total: None)
    report("remote_frames", 0, len(asset_ids))
    with RemoteFactsClient(config) as remote, PendingHeadFacts(HeadFactStore(store)) as bank:
        for index, asset_id in enumerate(asset_ids, 1):
            answers, kinds = _read_clip(
                remote,
                frame_paths.get(asset_id, ()),
                preview_paths.get(asset_id) if asset_id in exposure else None,
                exposure=asset_id in exposure,
                kinds=asset_id in clips,
                concurrency=config.facts_concurrency,
                check=check,
            )
            rows = _aggregate(
                answers, kinds, exposure=asset_id in exposure, kinds=asset_id in clips
            )
            check()
            for key, fact in rows:
                bank.add(asset_id, [fact], encoder_key=key)
            # A completed clip must be durable before a watcher counts it.
            bank.flush()
            report("remote_frames", index, len(asset_ids))
            charged.extend(a.service_seconds for a in answers if a.service_seconds is not None)
    return sum(charged) if charged else None


def _read_clip(remote, paths, preview, *, exposure, kinds, concurrency, check):
    versions = {}
    if exposure:
        versions[MARQO_HEAD] = MARQO_VERSION
    if kinds:
        versions["frame_kind"] = "public-v1"
    requests = [(path.read_bytes(), versions) for path in paths]
    if preview is not None:
        requests.append((preview.read_bytes(), {MARQO_HEAD: MARQO_VERSION}))
    check()
    # At most one clip's eight frames and preview are queued. Both models share
    # each frame upload; the configured window also bounds simultaneous requests.
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="frame-facts") as pool:
        answers = []
        for answer in pool.map(remote.facts, (r[0] for r in requests), (r[1] for r in requests)):
            check()
            answers.append(answer)
    return answers, answers[: len(paths)]


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
