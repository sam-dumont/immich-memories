"""A remembered answer remains visible while its batch reaches the store."""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest
from sqlalchemy.exc import OperationalError

from immich_memories.cache import judgment_cache
from tests.annotation_rows import annotation_store, read_rows


@pytest.mark.parametrize(
    ("action", "expected"),
    [("read", "remembered answer"), ("forget", None), ("replace", "newer answer")],
)
def test_an_in_flight_flush_keeps_answers_and_later_changes_in_order(monkeypatch, action, expected):
    cache = judgment_cache.JudgmentCache(annotation_store())
    cache.remember("question", "remembered answer")
    writing, release, reading = Event(), Event(), Event()
    real_write = judgment_cache.bank_rows

    def delayed_write(*args, **kwargs):
        writing.set()
        assert release.wait(5)
        return real_write(*args, **kwargs)

    def read():
        reading.set()
        if action == "forget":
            cache.forget("question")
        elif action == "replace":
            cache.remember("question", "newer answer")
            cache.flush()
        return cache.answer_for("question")

    # WHY: Pause only the database WRITE boundary; reads use the real store.
    monkeypatch.setattr(judgment_cache, "bank_rows", delayed_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        flush = pool.submit(cache.flush)
        try:
            assert writing.wait(5)
            answer = pool.submit(read)
            assert reading.wait(5)
            try:
                answer.result(timeout=0.2)
            except TimeoutError:
                pass
        finally:
            release.set()
        flush.result(timeout=5)
        assert answer.result(timeout=5) == expected
    rows = read_rows(annotation_store(), "judgments")
    assert [row["answer"] for row in rows] == ([] if expected is None else [expected])


def _locked() -> OperationalError:
    """What SQLite says when another connection holds the write lock past the busy timeout."""
    return OperationalError(
        "INSERT INTO judgments", {}, sqlite3.OperationalError("database is locked")
    )


def test_a_briefly_busy_store_keeps_the_answers_and_writes_them_on_the_next_flush(monkeypatch):
    """A lock that clears costs a retry, never the answers someone paid for."""
    cache = judgment_cache.JudgmentCache(annotation_store())
    cache.answer_for("anything")  # the bank now knows which questions the store holds
    real_write = judgment_cache.bank_rows
    calls = []

    def busy_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _locked()
        return real_write(*args, **kwargs)

    # WHY: the database WRITE boundary fails once, as a busy SQLite file does.
    monkeypatch.setattr(judgment_cache, "bank_rows", busy_once)
    for index in range(judgment_cache.FLUSH_ROWS):
        cache.remember(f"q-{index}", f"answer-{index}")

    assert cache.answer_for("q-0") == "answer-0"
    cache.remember("q-0", "newer answer")
    cache.flush()

    stored = {row["key"]: row["answer"] for row in read_rows(annotation_store(), "judgments")}
    assert len(stored) == judgment_cache.FLUSH_ROWS
    assert stored["q-0"] == "newer answer"
    assert stored["q-1"] == "answer-1"


def test_a_store_that_stays_locked_drops_the_answers_with_a_warning(monkeypatch, caplog):
    """Fail open, but say so, keep nothing in memory and never claim the answer is held."""
    cache = judgment_cache.JudgmentCache(annotation_store())
    cache.answer_for("anything")
    calls = []

    def always_locked(*_args, **_kwargs):
        calls.append(1)
        raise _locked()

    # WHY: the database WRITE boundary never recovers.
    monkeypatch.setattr(judgment_cache, "bank_rows", always_locked)
    monkeypatch.setattr(judgment_cache, "RETRY_PAUSE_SECONDS", 0.0)
    cache.remember("question", "answer")
    with caplog.at_level(logging.WARNING, logger=judgment_cache.__name__):
        cache.flush()

    assert len(calls) == judgment_cache.MAX_WRITE_ATTEMPTS
    assert cache.answer_for("question") is None
    assert "1 answers" in caplog.text
    assert "database is locked" in caplog.text
    assert read_rows(annotation_store(), "judgments") == []
