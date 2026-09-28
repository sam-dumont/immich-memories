"""The library's own account of a period, read by a film that never writes it."""

from __future__ import annotations

import json

from immich_memories.store.library_overviews import library_period_account
from tests.annotation_rows import add_rows, annotation_store


def _bank(rows):
    store = annotation_store()
    add_rows(
        store,
        "library_overviews",
        *[
            {
                "node_key": key,
                "kind": kind,
                "period": period,
                "account": account,
                "children": json.dumps(children),
            }
            for key, kind, period, account, children in rows
        ],
    )
    return store


def test_a_library_with_no_overview_table_has_no_account():
    assert library_period_account(annotation_store(), "2024-02") == ""


def test_the_fuller_revision_of_a_period_is_the_account():
    store = _bank(
        [
            ("n1", "month", "2024-02", "a short reading", ["e1"]),
            ("n2", "month", "2024-02", "a reading over more of the month", ["e1", "e2", "e3"]),
            ("n3", "month", "2024-03", "another month entirely", ["e9"]),
        ]
    )
    assert library_period_account(store, "2024-02") == "a reading over more of the month"


def test_parts_of_a_period_are_joined_in_node_key_order():
    store = _bank(
        [
            ("n2", "month-part", "2024-02", "the second half", ["e2"]),
            ("n1", "month-part", "2024-02", "the first half", ["e1"]),
        ]
    )
    assert library_period_account(store, "2024-02") == "the first half\n\nthe second half"


def test_a_blank_account_is_no_account():
    store = _bank([("n1", "month", "2024-02", "   ", ["e1"])])
    assert library_period_account(store, "2024-02") == ""
