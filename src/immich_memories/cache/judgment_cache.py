"""Answers to judgement-call prompts, keyed by exactly what was asked.

A judgement call is the expensive kind: reasoning mode costs 5-10x the latency
and 10-20x the completion tokens of a fast answer. The refinement loop asks the
same question repeatedly — a stabilize round that changes nothing re-presents
an identical selection, and a second run of the same memory presents it again.

Reusing the answer is the point rather than a compromise. A good judgement
about an identical set should not be re-rolled, and a sampled verdict that
changes between two identical rounds is noise, not a second opinion.

The answers live in the store (`judgments`), because an answer someone paid for is
worth keeping; emptying the table costs only the calls it saved. A pair-batch pool
answers many questions at once, and a transaction per answer is a round trip per answer
on PostgreSQL, so answers are written in batches (`FLUSH_ROWS`, or `FLUSH_SECONDS` after
the first one waits) and a crash costs at most one batch. The bank also knows which
questions it holds, so a question it never answered costs no read at all.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.db import Store, now_db, open_store
from immich_memories.db.tables import judgments, text_completion_failures
from immich_memories.store.batches import bank_rows

if TYPE_CHECKING:
    from datetime import datetime

    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

# Bump to abandon every stored answer — for a change in how the answer is used
# that the prompt text itself does not capture.
_ANSWER_VERSION = "judge1"
# Bump when the shared visual gateway changes what identity material the
# provider actually sees. visual1 keyed annotations without sending them.

FLUSH_ROWS = 64
FLUSH_SECONDS = 2.0
# How stale this process's list of banked questions may get before it asks for newer ones.
KNOWN_REFRESH_SECONDS = 5.0


def judgment_key(
    *, model: str | None, prompt: str, thinking: bool, thinking_identity: str = ""
) -> str:
    """Everything that could change the answer, and nothing that could not.

    The prompt text carries the clips, their descriptions and their order, so
    a changed selection keys differently without anyone maintaining a list of
    what to invalidate on. It also carries the prompt template, so editing the
    wording abandons the answers given to the old one — which is the behaviour
    you want and the one that is easiest to forget to implement.
    """
    parts = [_ANSWER_VERSION, model or "", "thinking" if thinking else "fast", prompt]
    if thinking_identity:
        parts.append(thinking_identity)
    material = "\x1f".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def judgment_bank(config: Config | None = None) -> Store:
    """Where reused answers live: the store this configuration names."""
    return open_store(config)


class _Bank:
    """One store's answers in this process: pending writes and the questions it holds."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._pending: dict[str, dict[str, object]] = {}
        self._timer: threading.Timer | None = None
        self._known: set[str] | None = None
        self._watermark: datetime | None = None
        self._checked = 0.0

    def answer_for(self, key: str) -> str | None:
        with self._lock:
            if key in self._pending:
                return str(self._pending[key]["answer"])
            if key not in self._known_keys():
                return None
        with self._store.connect() as connection:
            answer = connection.execute(
                sa.select(judgments.c.answer).where(judgments.c.key == key)
            ).scalar()
        return None if answer is None else str(answer)

    def remember(self, key: str, answer: str) -> None:
        with self._lock:
            self._pending[key] = {"key": key, "answer": answer, "answered_at": now_db()}
            if self._known is not None:
                self._known.add(key)
            if len(self._pending) >= FLUSH_ROWS:
                self.flush()
            elif self._timer is None:
                self._timer = threading.Timer(FLUSH_SECONDS, self.flush)
                self._timer.daemon = True
                self._timer.start()

    def forget(self, key: str) -> None:
        with self._lock:
            self._pending.pop(key, None)
            if self._known is not None:
                self._known.discard(key)
        with self._store.begin() as connection:
            connection.execute(sa.delete(judgments).where(judgments.c.key == key))

    def flush(self) -> None:
        with self._lock:
            rows, self._pending = list(self._pending.values()), {}
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if not rows:
            return
        try:
            bank_rows(self._store, judgments, rows, keys=("key",))
        except SQLAlchemyError as exc:
            logger.debug("Judgment cache unwritable (%s): %d answers not kept", exc, len(rows))

    def _known_keys(self) -> set[str]:
        """The questions the store holds, read once and then only what is newer."""
        if self._known is not None and time.monotonic() - self._checked < KNOWN_REFRESH_SECONDS:
            return self._known
        query = sa.select(judgments.c.key, judgments.c.answered_at)
        if self._known is not None and self._watermark is not None:
            # A second of overlap: two writers' clocks and commit order are not one sequence.
            query = query.where(judgments.c.answered_at >= self._watermark - timedelta(seconds=1))
        with self._store.connect() as connection:
            rows: list[Any] = list(connection.execute(query))
        known = set() if self._known is None else self._known
        known.update(str(row[0]) for row in rows)
        stamps = [row[1] for row in rows if row[1] is not None]
        if stamps:
            self._watermark = max([*stamps, *([self._watermark] if self._watermark else [])])
        self._known, self._checked = known, time.monotonic()
        return known


_banks: dict[tuple[str, str | None], _Bank] = {}
_banks_lock = threading.Lock()


def _bank_for(store: Store) -> _Bank:
    key = (store.location.url, store.schema)
    with _banks_lock:
        bank = _banks.get(key)
        if bank is None or bank._store is not store:
            bank = _banks[key] = _Bank(store)
        return bank


def flush_judgments() -> None:
    """Write every answer this process still holds; a run's end and the interpreter's exit."""
    with _banks_lock:
        banks = list(_banks.values())
    for bank in banks:
        bank.flush()


atexit.register(flush_judgments)
if hasattr(os, "register_at_fork"):
    # A forked child's pending answers are its parent's to write.
    os.register_at_fork(after_in_child=_banks.clear)


class JudgmentCache:
    """Remembers what the model said about an identical question.

    Every failure here is quiet and costs only calls: an unreachable store, a
    locked database or a damaged row must never take a generation down with it.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        self._bank = _bank_for(store)

    def answer_for(self, key: str) -> str | None:
        """What the model said last time, or None if it has not been asked."""
        try:
            return self._bank.answer_for(key)
        except SQLAlchemyError as exc:
            logger.debug("Judgment cache unreadable (%s): asking again", exc)
            return None

    def remember(self, key: str, answer: str) -> None:
        """Keep an answer. Silence and failures are never stored."""
        if answer:
            self._bank.remember(key, answer)

    def forget(self, key: str) -> None:
        """Drop an answer the asking contract refused, so the question is asked again."""
        try:
            self._bank.forget(key)
        except SQLAlchemyError as exc:
            logger.debug("Judgment cache unwritable (%s): the answer is still kept", exc)

    def flush(self) -> None:
        """Write the answers still waiting for their batch."""
        self._bank.flush()

    def completion_failure_for(self, key: str) -> dict | None:
        """Replay a bounded output failure separately; it is never a usable answer."""
        t = text_completion_failures
        try:
            with self._store.connect() as connection:
                raw = connection.execute(sa.select(t.c.record).where(t.c.key == key)).scalar()
            record = json.loads(raw) if raw else None
            return record if isinstance(record, dict) else None
        except (SQLAlchemyError, ValueError) as exc:
            logger.debug("Completion failure cache unreadable (%s)", exc)
            return None

    def remember_completion_failure(self, key: str, record: dict) -> None:
        """Only the text gateway supplies verified exhausted-completion records."""
        row = {"key": key, "record": json.dumps(record), "recorded_at": now_db()}
        try:
            bank_rows(self._store, text_completion_failures, [row], keys=("key",))
        except SQLAlchemyError as exc:
            logger.debug("Completion failure was not kept (%s)", exc)
