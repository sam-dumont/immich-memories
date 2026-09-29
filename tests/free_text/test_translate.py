"""The whole translation: a sentence read, linked and pooled against a library."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from immich_memories.db import open_store
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household
from immich_memories.free_text.trace import explain, save_with_run
from immich_memories.free_text.translate import household_of, translate
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.tracking.run_observations import observe_run
from immich_memories.tracking.span_store import SpanStore
from tests.free_text.banked import QuestionAsker

TODAY = date(2026, 9, 1)
NOBODY = Household({})


def _picture(asset_id: str, day: date, caption: str) -> LibraryPicture:
    taken_at = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return LibraryPicture(asset_id, taken_at, "photo", caption=caption)


def _library() -> LibraryView:
    first = date(2019, 1, 1)
    cats = [
        _picture(f"cat-{n}", first + timedelta(days=40 * n), "A black cat is sleeping")
        for n in range(14)
    ]
    dogs = [_picture(f"dog-{n}", first + timedelta(days=n), "A dog on a beach") for n in range(5)]
    pictures = sorted(cats + dogs, key=lambda picture: picture.taken_at)
    return LibraryView(pictures=tuple(pictures), people={}, sharpness_line=None)


def _read(what: list[str], when: list[str]) -> dict[str, Any]:
    return {"who": [], "when": when, "where": [], "what": what}


ANSWERS: dict[str, Any] = {
    "Split the owner's request": _read(["our cat"], ["along the years"]),
    "Give the date range": {"date_from": None, "date_to": None},
    "one single occasion": {"reason": "banked", "choice": "many occasions"},
    "name the main subject itself too": {"reason": "banked", "choices": []},
}


def test_a_sentence_becomes_the_pool_of_pictures_whose_captions_are_about_it(
    lexicon: Lexicon,
) -> None:
    # WHY: stands in for the model server answering the translation's questions.
    asker = QuestionAsker(ANSWERS)

    asked = translate("our cat along the years", _library(), NOBODY, lexicon, asker, today=TODAY)

    assert asked.translation.subject.main == ("cat",)
    assert asked.translation.when.start is None
    assert {picture.asset_id for picture in asked.pool.pictures} == {f"cat-{n}" for n in range(14)}
    assert asked.pool.verdict == "possible"


def test_the_trace_prints_one_line_per_decision_with_the_words_and_the_rule(
    lexicon: Lexicon,
) -> None:
    # WHY: stands in for the model server answering the translation's questions.
    asked = translate(
        "our cat along the years", _library(), NOBODY, lexicon, QuestionAsker(ANSWERS), today=TODAY
    )

    lines = explain(asked).splitlines()
    heads = [line.split()[0] for line in lines[1:] if line and not line.startswith(" ")]

    assert lines[0] == '"our cat along the years"'
    assert heads == ["READING", "WHO", "WHEN", "WHERE", "WHAT", "POOL", "VERDICT"]
    assert "what: our cat" in lines[1] and "when: along the years" in lines[1]
    assert any("answer 1:" in line for line in lines)
    assert any(line.startswith("WHERE") and "anywhere" in line for line in lines)
    assert any(line.startswith("POOL") and "subject 14" in line for line in lines)
    assert any("many occasions 3/3" in line for line in lines)
    assert lines[-1].startswith("VERDICT  possible: 14 pictures")


def test_the_household_is_the_people_file_its_owner_and_the_homes_the_pictures_show() -> None:
    view = LibraryView(pictures=(), people={}, sharpness_line=None, owner_id="p-owner")

    household = household_of(view, home_base=(50.5, 4.25))

    assert household.owner_id == "p-owner"
    assert [(home.latitude, home.longitude) for home in household.homes] == [(50.5, 4.25)]
    assert household_of(view).homes == ()


def test_the_trace_is_saved_with_the_run_where_the_report_finds_it(
    lexicon: Lexicon, tmp_path: Path
) -> None:
    store = open_store()
    # WHY: stands in for the model server answering the translation's questions.
    asked = translate(
        "our cat along the years", _library(), NOBODY, lexicon, QuestionAsker(ANSWERS), today=TODAY
    )
    trace = explain(asked)

    with observe_run(store, source="manual", capture_system=False) as tracker:
        record_run_attempt(tracker.run_id, tmp_path, "", store=store)
        save_with_run(asked, None, trace)

    saved = SpanStore(store).diagnostics(tracker.run_id)["free_text"]
    assert saved["request"] == "our cat along the years"
    assert saved["trace"] == trace
    assert saved["funnel"]["pool"] == 14
    assert (tmp_path / "free-text-trace.private.txt").read_text() == trace
