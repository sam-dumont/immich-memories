"""The editor's evidence line names the first picture apart from regularity (#2798).

"here since <onset>" read as "known since" for somebody photographed now and then for
years; the onset leaves out pictures from before somebody was part of the owner's life,
which is a different fact from when the library first shows them. Invented people only.
"""

from __future__ import annotations

from immich_memories.people.editor import load_people
from tests.people_registry_seed import seed_people


def _line(**evidence: object) -> str:
    store = seed_people(
        {
            "version": 1,
            "people": [
                {
                    "ids": ["id-alex"],
                    "name": "Alex Example",
                    "inferred": {
                        "tier": "recurring",
                        "evidence": {"count": 62, "active_months": 9, **evidence},
                        "links": [],
                    },
                }
            ],
        }
    )
    return load_people(store)[0].evidence


def test_the_first_picture_and_regular_since_are_two_facts():
    assert _line(first_month="2004-08", onset="2025-05") == (
        "62 pictures across 9 months, first picture 2004-08, regular since 2025-05"
    )


def test_an_onset_in_the_first_month_adds_nothing():
    assert _line(first_month="2004-08", onset="2004-08") == (
        "62 pictures across 9 months, first picture 2004-08"
    )


def test_without_an_onset_only_the_first_picture_is_given():
    assert _line(first_month="2004-08") == "62 pictures across 9 months, first picture 2004-08"


def test_without_any_month_only_the_counts_remain():
    assert _line() == "62 pictures across 9 months"
