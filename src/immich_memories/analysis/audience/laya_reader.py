"""Laya, a small local text classifier, answering the audience check's activity question.

The audience gate asks one question per carrier: does its caption describe one of the
eight private activities (a bath, a nappy change, breastfeeding, ...). Laya (a 0.4B ModernBERT
encoder, Apache-2.0, fine-tuned on public CC BY captions labelled in both orders by a hosted reader
under the production question) answers it from the compact caption in about 14 ms, on Apple silicon.

It answers that question without a prose LLM. Everything around it stays: detector and body holds are
applied before and after it and are never lifted, the parser's support checks read its finding as they
read any finding, and a carrier it does not answer stays held to the family. It reads the
compact caption the preparation seat wrote, the same text it was trained on, and never the picture
observations the vision reader may have added.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tarfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

# The question texts are part of the trained weights: change one and the weights no longer
# answer the question they were trained on.
AUDIENCE_FINDINGS = {
    "none": "no matching content is described",
    "breastfeeding_or_expressing_milk": (
        "a person breastfeeding or pumping milk; holding a baby or a bottle is not"
    ),
    "bathing": "a person in a bath, tub, sink or shower; a pool, the sea or water play is not",
    "toileting_or_changing": "using a toilet or potty, or a diaper change",
    "intimate_hygiene": "washing or wiping private body parts",
    "nudity_shirtless_or_underwear": (
        "a person nude, shirtless or only in underwear; a tank top is clothing"
    ),
    "identifying_record": "an ID card, patient wristband or readable private record",
    "graphic_medical_procedure": "surgery or delivery in progress, or an open wound",
    "sexual_content": "sexual activity or explicitly sexual posing",
    "adult_changing": "an adult undressing with private body exposed",
}
AUDIENCE_QUESTION = {
    "type": "choice",
    "instructions": "Which content does this image caption describe?",
    "criteria": AUDIENCE_FINDINGS,
}
_NUDITY = "nudity_shirtless_or_underwear"

logger = logging.getLogger(__name__)

# Captions whose scores one reader keeps; a year's film reads a few thousand.
_SCORED_LIMIT = 50_000


class LayaScorer(Protocol):
    """Option probabilities for one question over many states, in the question's option order."""

    def probabilities(
        self, states: Sequence[str], question: Mapping[str, Any]
    ) -> list[list[float]]: ...


class LayaReader:
    """The audience check's activity question, answered by a Laya scorer at a fixed threshold."""

    def __init__(self, scorer: LayaScorer, *, threshold: float, checkpoint_id: str) -> None:
        self._scorer = scorer
        self._threshold = threshold
        backend = getattr(scorer, "cache_backend", None) or (
            f"{type(scorer).__module__}.{type(scorer).__qualname__}"
        )
        self.cache_identity = f"laya|{backend}|{checkpoint_id}|threshold={threshold.hex()}"
        # Option probabilities by caption text: the only thing the scores depend on. A
        # carrier's evidence key also changes when a later round banks a head or a neighbour's
        # exposure run, and a key the library never kept is asked again; the text is not.
        self._scored: dict[str, list[float]] = {}

    def close(self) -> None:
        """Release loaded weights; a later audience check loads the same scorer again."""
        if close := getattr(self._scorer, "close", None):
            close()

    def _probabilities(self, states: Sequence[str]) -> list[list[float]]:
        """Each state's probabilities, scoring only the texts this reader has not scored."""
        fresh = [state for state in dict.fromkeys(states) if state not in self._scored]
        if fresh:
            found = self._scorer.probabilities(fresh, AUDIENCE_QUESTION)
            self._scored.update(zip(fresh, found, strict=True))
        scored = [self._scored[state] for state in states]
        # Bounded for a long-lived server; the oldest texts go first.
        while len(self._scored) > _SCORED_LIMIT:
            del self._scored[next(iter(self._scored))]
        return scored

    def activity_answers(self, pending: Mapping[str, tuple[Sequence[str], bool]]) -> dict[str, str]:
        """Each carrier's activity answer, in the JSON form the audience check reads.

        `pending` maps a carrier's check key to its members' compact captions and whether the
        nudity finding may be answered for it. A carrier whose hold probability reaches the
        threshold gets its likeliest hold finding; every other carrier gets `none`. A carrier
        with no caption is left out and stays held to the family without an LLM fallback.
        """
        keys = [key for key, (captions, _allow) in pending.items() if any(captions)]
        if not keys:
            return {}
        found = self._probabilities(["\n".join(c for c in pending[key][0] if c) for key in keys])
        answers = {}
        for key, probabilities in zip(keys, found, strict=True):
            allowed = pending[key][1]
            held = {
                name: p
                for name, p in zip(AUDIENCE_FINDINGS, probabilities, strict=True)
                if name != "none" and (allowed or name != _NUDITY)
            }
            hold = sum(held.values())
            finding = max(held, key=held.__getitem__) if hold >= self._threshold else "none"
            answers[key] = json.dumps({"finding": finding, "why": f"laya hold p={hold:.3f}"})
        return answers


class MlxLayaScorer:
    """Laya on Apple silicon through `laya-mlx`, loaded on first use."""

    # The audience bank keys its answers by this name (`LayaReader.cache_identity`): the module
    # path the scorer had when those answers were banked, kept so moving the code re-asks nothing.
    cache_backend = "immich_memories.analysis.audience.laya_reader.MlxLayaScorer"

    def __init__(self, checkpoint: Path, *, batch_size: int = 16) -> None:
        self._checkpoint = checkpoint
        self._batch_size = batch_size
        self._agent: Any = None

    def close(self) -> None:
        """Drop the agent's live MLX tensors before the runtime cache is emptied."""
        self._agent = None

    def probabilities(
        self, states: Sequence[str], question: Mapping[str, Any]
    ) -> list[list[float]]:
        import mlx.core as mx  # type: ignore[import-not-found,import-untyped,unused-ignore]
        import numpy as np
        from laya_mlx.agent import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
            Agent,
            collate_items,
        )
        from laya_mlx.common import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
            QTYPES,
            build_sequence,
        )

        if self._agent is None:
            self._agent = Agent(
                str(self._checkpoint), dtype="bfloat16", batch_size=self._batch_size
            )
        agent = self._agent
        internal = {
            "t": question["type"],
            "ins": question["instructions"],
            "crit": question.get("criteria"),
        }
        items = []
        for state in states:
            ids, markers = build_sequence(
                agent.tok, state, internal, agent.cfg["max_len"], agent.cfg["head_max_len"]
            )
            items.append({"ids": ids, "markers": markers, "qtype": QTYPES[question["type"]]})
        out: list[list[float]] = [[] for _ in items]
        # Shortest first, so a batch pads to its neighbours rather than to the longest caption.
        order = sorted(range(len(items)), key=lambda i: len(items[i]["ids"]))
        for start in range(0, len(order), self._batch_size):
            chunk = order[start : start + self._batch_size]
            batch = collate_items([items[i] for i in chunk], agent.tok.pad_token_id)
            logits = np.asarray(agent.forward(batch)[0].astype(mx.float32))
            for row, i in enumerate(chunk):
                z = logits[row, : len(items[i]["markers"])]
                e = np.exp(z - z.max())
                out[i] = (e / e.sum()).tolist()
        return out


def unpack_checkpoint(archive: Path, destination: Path) -> Path:
    """Unpack the fetched checkpoint archive next to it, once, and return its directory.

    Only regular files whose names stay inside the destination are written; the archive is
    digest-pinned, but a path that climbs out of the folder is refused rather than trusted.
    """
    if (destination / "model.safetensors").is_file() or (
        (destination / "model.onnx").is_file() and (destination / "model.onnx.data").is_file()
    ):
        return destination
    root = destination.resolve()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (root / member.name).resolve()
            if not member.isfile() or not target.is_relative_to(root):
                continue
            source = bundle.extractfile(member)
            if source is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as out:
                    out.write(source.read())
    return destination


def checkpoint_identity(checkpoint: Path) -> str:
    """Fingerprint the files actually loaded, including local replacements of pinned weights."""
    files = {}
    for path in sorted(checkpoint.rglob("*")):
        if path.is_file():
            with path.open("rb") as content:
                files[str(path.relative_to(checkpoint))] = hashlib.file_digest(
                    content, "sha256"
                ).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def laya_reader_for(editorial_config) -> LayaReader | None:
    """The configured Laya reader, or None when it is off or cannot run here.

    A tier that turns Laya on still cuts without it: the heads and the rules answer the sharing
    question alone, and one line says what is missing.
    """
    if not editorial_config.laya_audience:
        return None
    archive = editorial_config.laya_checkpoint_path
    if not archive.exists():
        logger.warning(
            "Laya is on but %s is missing, so the heads and rules decide sharing alone: "
            "run `immich-memories models fetch`",
            archive,
        )
        return None
    checkpoint = (
        archive if archive.is_dir() else unpack_checkpoint(archive, archive.with_suffix(""))
    )
    threshold = editorial_config.laya_audience_threshold
    # One reader per checkpoint and threshold for the process: each edit asks for one, and
    # a new one would hash the weights again and score captions the last one already scored.
    key = (str(checkpoint), _file_signature(checkpoint), threshold)
    with _READERS_LOCK:
        reader = _READERS.get(key)
    if reader is None:
        reader = _new_reader(checkpoint, threshold)
        if reader is not None:
            with _READERS_LOCK:
                reader = _READERS.setdefault(key, reader)
    return reader


_READERS: dict[tuple[Any, ...], LayaReader] = {}
_READERS_LOCK = threading.Lock()


def _file_signature(checkpoint: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (str(path.relative_to(checkpoint)), stat.st_size, stat.st_mtime_ns)
        for path in sorted(checkpoint.rglob("*"))
        if path.is_file() and (stat := path.stat())
    )


def _new_reader(checkpoint: Path, threshold: float) -> LayaReader | None:
    if (checkpoint / "model.onnx").is_file():
        from immich_memories.analysis.audience.laya_onnx import OnnxLayaScorer

        return LayaReader(
            OnnxLayaScorer(checkpoint),
            threshold=threshold,
            checkpoint_id=checkpoint_identity(checkpoint),
        )
    try:
        import laya_mlx  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: F401
    except ImportError:
        logger.warning(
            "Laya is on but laya-mlx is not installed, so the heads and rules decide sharing "
            "alone. Install laya-mlx in the app environment; for uv tool: "
            '`uv tool install "immich-memories[all-mac]" --with laya-mlx` (Apple silicon)'
        )
        return None
    return LayaReader(
        MlxLayaScorer(checkpoint),
        threshold=threshold,
        checkpoint_id=checkpoint_identity(checkpoint),
    )
