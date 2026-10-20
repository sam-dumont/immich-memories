"""The whole translation: a sentence read, linked and pooled against a library."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from immich_memories.db import open_store
from immich_memories.free_text.handoff import film_for
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


def test_prepare_window_is_called_with_the_linked_dates_and_its_view_replaces_the_stale_one(
    lexicon: Lexicon,
) -> None:
    """#2045: a request's own dates reach the hook before anything reads captions with them."""
    stale = LibraryView(pictures=(), people={}, sharpness_line=None)
    seen: list[Any] = []

    def prepare_window(when, place):
        seen.append(when)
        return _library(), {}, {}

    asked = translate(
        "our cat along the years",
        stale,
        NOBODY,
        lexicon,
        QuestionAsker(ANSWERS),
        today=TODAY,
        prepare_window=prepare_window,
    )

    assert seen and seen[0].start is None and seen[0].end is None
    # The stale, empty view never reaches the pool: prepare_window's own view does.
    assert {picture.asset_id for picture in asked.pool.pictures} == {f"cat-{n}" for n in range(14)}


def test_a_subject_with_no_caption_words_never_asks_to_prepare_its_window(lexicon: Lexicon) -> None:
    """#2045 (owner review): a person or a computed selection reads faces and GPS, never a
    caption, so it never pays to prepare a window -- only a caption-only subject does."""
    answers = {**ANSWERS, "Split the owner's request": _read([], ["along the years"])}

    def prepare_window(when, place):
        raise AssertionError("no caption-dependent subject: this must never be called")

    translate(
        "my photos along the years",
        _library(),
        NOBODY,
        lexicon,
        QuestionAsker(answers),
        today=TODAY,
        prepare_window=prepare_window,
    )


def test_the_subject_is_rebuilt_after_preparation_so_a_first_run_matches_a_second(
    lexicon: Lexicon,
) -> None:
    """#2045 (Opus review, BLOCKER): `build_subject` reads the WordNet kinds the library's
    own captions use; an unprepared first run's empty captions must not leave it with a
    narrower subject than a second run, already prepared, would get."""
    uncaptioned = LibraryView(
        pictures=tuple(replace(picture, caption=None) for picture in _library().pictures),
        people={},
        sharpness_line=None,
    )

    first_run = translate(
        "our cat along the years",
        uncaptioned,
        NOBODY,
        lexicon,
        QuestionAsker(ANSWERS),
        today=TODAY,
        prepare_window=lambda _when, _place: (_library(), {}, {}),
    )
    second_run = translate(
        "our cat along the years", _library(), NOBODY, lexicon, QuestionAsker(ANSWERS), today=TODAY
    )

    assert first_run.translation.subject == second_run.translation.subject
    assert {p.asset_id for p in first_run.pool.pictures} == {
        p.asset_id for p in second_run.pool.pictures
    }


def test_a_company_word_alone_still_asks_to_prepare_its_window(lexicon: Lexicon) -> None:
    """#2045 (Opus review B): "with friends" reads captions too (`_company` in pool.py),
    even with no subject word of its own -- the one predicate has to catch it or "me with
    friends in 2023" keeps answering as if nothing can be prepared."""
    answers = {
        **ANSWERS,
        "Split the owner's request": {
            "who": ["friends"],
            "when": ["in 2023"],
            "where": [],
            "what": [],
        },
    }
    seen: list[Any] = []

    def prepare_window(when, place):
        seen.append(when)
        return _library(), {}, {}

    translate(
        "me with friends in 2023",
        LibraryView(pictures=(), people={}, sharpness_line=None),
        Household({}),
        lexicon,
        QuestionAsker(answers),
        today=TODAY,
        prepare_window=prepare_window,
    )

    assert seen, "company ('with friends') reads captions, so the window must be checked"


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


@pytest.mark.parametrize("weather", ["rainy", "foggy", "sunny", "snowy"])
@pytest.mark.parametrize("part", ["when", "what"])
def test_weather_labelled_as_time_still_restricts_the_pool(lexicon, weather, part):
    # WHY: the reader classified visible weather under when; the date reader cannot date it.
    answers = {
        **ANSWERS,
        "Split the owner's request": _read(
            [f"{weather} days"] if part == "what" else [],
            [f"{weather} days"] if part == "when" else [],
        ),
        "mainly show": {"reason": "weather", "choices": [weather]},
        "main subject (subject)": {"reason": "weather", "choice": "an activity or event"},
    }
    view = LibraryView(
        (
            _picture("wet", TODAY, f"A {weather} afternoon in the park."),
            _picture("dry", TODAY, "A dog sleeps on a sofa."),
        ),
        {},
        None,
    )
    asked = translate(f"{weather} days", view, NOBODY, lexicon, QuestionAsker(answers), today=TODAY)
    assert {p.asset_id for p in asked.pool.pictures} == {"wet"}
    assert weather in asked.translation.subject.words


def test_weather_split_between_time_and_subject_keeps_the_adjective(lexicon):
    # WHY: a real provider called only "days" time and only "foggy" the subject.
    answers = {
        **ANSWERS,
        "Split the owner's request": _read(["foggy"], ["days"]),
        "mainly show": {"reason": "weather", "choices": ["fog"]},
    }
    view = LibraryView(
        (
            _picture("fog", TODAY, "Fog fills the park."),
            _picture("dry", TODAY, "A dog sleeps indoors."),
        ),
        {},
        None,
    )
    asked = translate("foggy days", view, NOBODY, lexicon, QuestionAsker(answers), today=TODAY)
    assert {p.asset_id for p in asked.pool.pictures} == {"fog"}


def test_a_weather_noun_vote_keeps_the_requests_adjective_form(lexicon):
    # WHY: a real provider preferred the abstract noun "sunniness" to "sunny".
    answers = {
        **ANSWERS,
        "Split the owner's request": _read([], ["sunny days"]),
        "mainly show": {"reason": "weather", "choices": ["sunniness"]},
    }
    view = LibraryView(
        (
            _picture("sun", TODAY, "A sunny afternoon in the park."),
            _picture("dark", TODAY, "A dog sleeps indoors."),
        ),
        {},
        None,
    )
    asked = translate("sunny days", view, NOBODY, lexicon, QuestionAsker(answers), today=TODAY)
    assert {p.asset_id for p in asked.pool.pictures} == {"sun"}


def _party_library() -> LibraryView:
    first = date(2031, 2, 3)
    cakes = [
        _picture(f"cake-{n}", first + timedelta(days=60 * n), "A birthday cake with candles")
        for n in range(5)
    ]
    dogs = [_picture(f"dog-{n}", first + timedelta(days=n), "A dog on a beach") for n in range(5)]
    return LibraryView(pictures=tuple(cakes + dogs), people={}, sharpness_line=None)


def _cake_answers(what: str, when: str) -> dict[str, Any]:
    return {
        "Split the owner's request": _read([what], [when]),
        "Give the date range": {"date_from": "2031-01-01", "date_to": "2031-12-31"},
        "captions are written in English": {"reason": "banked", "english": "cakes"},
        "one single occasion": {"reason": "banked", "choice": "many occasions"},
        "name the main subject itself too": {"reason": "banked", "choices": []},
    }


def test_a_french_subject_finds_the_same_pictures_as_the_english_request(
    lexicon: Lexicon,
) -> None:
    """#2136: "gâteaux" matched against English captions found nothing. A subject word no
    caption uses is named in English by the reader before WordNet expands it."""
    # WHY: stands in for the model server answering the translation's questions.
    english = translate(
        "birthday cakes in 2031",
        _party_library(),
        NOBODY,
        lexicon,
        QuestionAsker(_cake_answers("birthday cakes", "in 2031")),
        today=TODAY,
    )
    french = translate(
        "les gâteaux d'anniversaire en 2031",
        _party_library(),
        NOBODY,
        lexicon,
        QuestionAsker(_cake_answers("les gâteaux d'anniversaire", "en 2031")),
        today=TODAY,
    )

    cakes = {f"cake-{n}" for n in range(5)}
    assert {picture.asset_id for picture in english.pool.pictures} == cakes
    assert {picture.asset_id for picture in french.pool.pictures} == cakes
    assert french.translation.subject.main == english.translation.subject.main == ("cakes",)


def _seaside_library() -> LibraryView:
    first = date(2031, 7, 1)
    shots = [
        ("scenic", "A sandy beach with waves under a blue sky"),
        ("toy", "A toy bucket on the beach"),
        ("play", "Children playing on the beach"),
        ("hills", "A landscape of hills and fields"),
    ]
    pictures = [
        _picture(f"{name}-{n}", first + timedelta(days=4 * n + offset), caption)
        for offset, (name, caption) in enumerate(shots)
        for n in range(4)
    ]
    return LibraryView(pictures=tuple(pictures), people={}, sharpness_line=None)


def _seaside_answers(what: str, other_names: list[str]) -> dict[str, Any]:
    return {
        "Split the owner's request": _read([what], ["in summer 2031"]),
        "Give the date range": {"date_from": "2031-06-21", "date_to": "2031-09-22"},
        "captions are written in English": {"reason": "banked", "english": what.split()[-1]},
        "one single occasion": {"reason": "banked", "choice": "many occasions"},
        "name the main subject itself too": {"reason": "banked", "choices": other_names},
    }


def _group(asked: Any) -> set[str]:
    return {picture.asset_id.split("-")[0] for picture in asked.pool.pictures}


def test_a_generic_name_the_model_offers_never_widens_a_place_subject(lexicon: Lexicon) -> None:
    """#2125: "the beach" widened to "landscape" pulled hills and fields into a beach film.
    A place is matched by its own words and WordNet's names for it; the beach shots,
    people at the beach included, stay."""
    # WHY: stands in for the model server, which names "landscape" as the beach too.
    asker = QuestionAsker(_seaside_answers("the beach", ["landscape"]))

    asked = translate(
        "the beach in summer 2031", _seaside_library(), NOBODY, lexicon, asker, today=TODAY
    )

    assert _group(asked) == {"scenic", "toy", "play"}


def test_a_place_word_the_model_infers_admits_the_place_not_objects_photographed_there(
    lexicon: Lexicon,
) -> None:
    """#2125: a scenery request inferred "beach"; matched anywhere in a caption, it let in a
    toy photographed on a beach. An inferred name must be what the caption is about."""
    # WHY: stands in for the model server, which names the beach as scenery.
    asker = QuestionAsker(_seaside_answers("the scenery", ["beach"]))

    asked = translate(
        "the scenery in summer 2031", _seaside_library(), NOBODY, lexicon, asker, today=TODAY
    )

    assert _group(asked) == {"scenic"}


def test_a_french_beach_without_the_children_films_the_beach_shots_with_no_children(
    lexicon: Lexicon,
) -> None:
    """#2138 and #2136 together: "sans les enfants" asks the children away, "plage" is the
    beach the captions write, and the film is the pool, not one unrelated day."""
    answers = {
        **_seaside_answers("la plage", []),
        "Split the owner's request": {
            "who": ["les enfants"],
            "when": ["en 2031"],
            "where": [],
            "what": ["la plage"],
        },
        "Give the date range": {"date_from": "2031-01-01", "date_to": "2031-12-31"},
        "captions are written in English": {"reason": "banked", "english": "beach"},
        "would be written on something": {"reason": "banked", "choices": []},
    }
    # WHY: stands in for the model server answering the translation's questions.
    asker = QuestionAsker(answers)

    asked = translate(
        "la plage sans les enfants en 2031", _seaside_library(), NOBODY, lexicon, asker, today=TODAY
    )
    film = film_for(asked, asker, events_on=lambda _day: [])

    assert (asked.translation.who.company, asked.translation.who.absent_company) == (
        None,
        "children",
    )
    assert _group(asked) == {"scenic", "toy"}
    assert film.route == "pool"
