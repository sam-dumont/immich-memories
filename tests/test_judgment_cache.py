"""A judgement about an identical question should not be paid for twice.

A second run of the same memory asks the model the same things again. In
reasoning mode each of those costs 5-10x the latency and 10-20x the tokens of a
fast call, so the bank keys every verdict by the exact question asked.
"""

import sqlalchemy as sa

from immich_memories.db import close_stores, open_store
from tests.annotation_rows import annotation_store, read_rows


def test_concurrent_banking_from_many_threads_keeps_every_answer() -> None:
    """Readers hammer one cache from a thread pool; nothing may be lost."""
    from concurrent.futures import ThreadPoolExecutor

    from immich_memories.cache.judgment_cache import JudgmentCache

    cache = JudgmentCache(annotation_store())

    def bank(worker: int) -> None:
        for index in range(25):
            key = f"k-{worker}-{index}"
            cache.remember(key, f"answer-{worker}-{index}")
            assert cache.answer_for(key) == f"answer-{worker}-{index}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(bank, range(8)))
    cache.flush()

    assert cache.answer_for("k-7-24") == "answer-7-24"
    assert len(read_rows(annotation_store(), "judgments")) == 200


def test_reasoning_dialect_is_part_of_the_question_even_at_the_same_prompt() -> None:
    """Two budgets are two different answers; only one of them may be replayed."""
    from immich_memories.cache.judgment_cache import judgment_key

    base = judgment_key(model="qwen", prompt="same evidence", thinking=True)

    assert base != judgment_key(model="qwen", prompt="same evidence", thinking=False)
    assert base != judgment_key(model="llama", prompt="same evidence", thinking=True)
    assert base != judgment_key(model="qwen", prompt="other evidence", thinking=True)
    assert base != judgment_key(
        model="qwen", prompt="same evidence", thinking=True, thinking_identity="budget=256"
    )


def test_a_bounded_failure_replays_without_ever_being_served_as_an_answer() -> None:
    """The stage must fall back again rather than read an exhausted attempt as a verdict."""
    from immich_memories.cache.judgment_cache import JudgmentCache

    cache = JudgmentCache(annotation_store())
    record = {"schema_version": "bounded-text-completion-v1", "attempts": [{"raw": ""}]}
    cache.remember_completion_failure("k", record)

    assert cache.completion_failure_for("k") == record
    assert cache.answer_for("k") is None
    assert cache.completion_failure_for("never-asked") is None


def test_answers_survive_the_store_being_closed_and_opened_again() -> None:
    """A later run, on a store opened afresh, reuses what an earlier one banked."""
    from immich_memories.cache.judgment_cache import JudgmentCache

    cache = JudgmentCache(annotation_store())
    cache.remember("k", "a")
    cache.flush()
    close_stores()

    assert JudgmentCache(open_store()).answer_for("k") == "a"


def test_a_store_that_cannot_hold_answers_costs_only_calls() -> None:
    """Losing the bank is a cost, never a failure, including on the failure table."""
    from immich_memories.cache.judgment_cache import JudgmentCache

    store = annotation_store()
    with store.begin() as connection:
        connection.execute(sa.text("DROP TABLE judgments"))
        connection.execute(sa.text("DROP TABLE text_completion_failures"))
    cache = JudgmentCache(store)

    cache.remember("k", "a")
    cache.flush()
    cache.remember_completion_failure("k", {"attempts": []})
    cache.forget("k")

    assert cache.answer_for("other") is None
    assert cache.completion_failure_for("k") is None
