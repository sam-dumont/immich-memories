"""Slow answers (suggestions, a year's trips) come back at once and are refreshed behind the page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from immich_memories.web.answer_cache import AnswerCache


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 28, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _cache(tmp_path: Path, clock: Clock, pending: list) -> AnswerCache:
    # The background work is queued here and run when the test says so.
    return AnswerCache(tmp_path, max_age=timedelta(hours=24), clock=clock, start=pending.append)


def test_a_first_ask_starts_the_work_and_a_later_ask_reads_the_answer(tmp_path):
    clock, pending = Clock(), []
    cache = _cache(tmp_path, clock, pending)
    asked = []

    first = cache.read("trips-2026", lambda: asked.append(1) or {"trips": [1]})
    assert (first.value, first.refreshing) == (None, True)

    pending.pop()()
    second = cache.read("trips-2026", lambda: asked.append(1) or {"trips": [2]})

    assert second.value == {"trips": [1]}
    assert second.refreshing is False
    assert second.computed_at == clock.now
    assert asked == [1]


def test_the_answer_outlives_the_server(tmp_path):
    clock, pending = Clock(), []
    _cache(tmp_path, clock, pending).read("k", lambda: {"v": 1})
    pending.pop()()

    again = _cache(tmp_path, clock, []).read("k", lambda: {"v": 2})

    assert again.value == {"v": 1}


def test_a_stale_or_refreshed_answer_is_shown_while_the_new_one_is_worked_out(tmp_path):
    clock, pending = Clock(), []
    cache = _cache(tmp_path, clock, pending)
    cache.read("k", lambda: {"v": 1})
    pending.pop()()

    clock.now += timedelta(hours=25)
    stale = cache.read("k", lambda: {"v": 2})
    assert (stale.value, stale.refreshing) == ({"v": 1}, True)
    # A second ask while that work runs does not start another.
    cache.read("k", lambda: {"v": 3})
    assert len(pending) == 1

    pending.pop()()
    asked = cache.read("k", lambda: {"v": 4}, refresh=True)
    assert (asked.value, asked.refreshing) == ({"v": 2}, True)


def test_a_failed_refresh_keeps_the_last_answer_and_says_why(tmp_path):
    clock, pending = Clock(), []
    cache = _cache(tmp_path, clock, pending)
    cache.read("k", lambda: {"v": 1})
    pending.pop()()

    def broken() -> dict:
        raise ConnectionError("Immich did not answer")

    cache.read("k", broken, refresh=True)
    pending.pop()()
    after = cache.read("k", lambda: {"v": 9})

    assert after.value == {"v": 1}
    assert after.error == "Immich did not answer"
    assert after.refreshing is False
