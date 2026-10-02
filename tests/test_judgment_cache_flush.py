"""A remembered answer remains visible while its batch reaches the store."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest

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
