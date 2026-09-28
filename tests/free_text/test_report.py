"""The free-text section of `immich-memories report`: what went wrong, with nothing private.

Every name, place, printed word and caption here is invented, and each is the thing the report
must not carry.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.free_text.handoff import film_for
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView
from immich_memories.free_text.trace import explain, save_with_run
from immich_memories.free_text.translate import Ask, household_of, translate
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.tracking.report_service import report_for_run
from immich_memories.tracking.run_observations import observe_run
from tests.free_text.banked import QuestionAsker

NAME, PLACE, PRINTED = "Quillamar", "Brackwater", "Thornfield"
CAPTION = "A cyclist in a Thornfield jersey waving beside the Quillamar farm gate"
REQUEST = f"{NAME} riding with the {PRINTED} club in {PLACE} since he was born"
BORN = "2012-03-04"
RIDER = LibraryPerson("p-rider", f"{NAME} Example", "son", date.fromisoformat(BORN))


def _picture(asset_id: str, at: datetime, caption: str, **fields: Any) -> LibraryPicture:
    return LibraryPicture(asset_id, at, "photo", caption=caption, **fields)


def _library() -> LibraryView:
    first = datetime(2021, 4, 3, 9, tzinfo=UTC)
    rides = [
        _picture(
            f"ride-{n}",
            first + timedelta(days=30 * n, minutes=10 * n),
            CAPTION,
            city=PLACE,
            country="Examplia",
            people=frozenset({"p-rider"}),
        )
        for n in range(14)
    ]
    return LibraryView(pictures=tuple(rides), people={"p-rider": RIDER}, sharpness_line=None)


class _Printed:
    # WHY: stands in for Immich's OCR search, a read of the server's text index.
    def pictures_reading(self, text: str) -> frozenset[str]:
        return frozenset({"ride-0", "ride-3"}) if text == PRINTED.lower() else frozenset()


ANSWERS: dict[str, Any] = {
    "Split the owner's request": {
        "who": [NAME.lower()],
        "when": ["since he was born"],
        "where": [f"in {PLACE.lower()}"],
        "what": [f"riding with the {PRINTED.lower()} club"],
    },
    "Does it give that time": {
        "reason": "banked",
        "is_age": False,
        "whose_age": RIDER.name,
        "age_from": 0,
        "age_to": 0,
    },
    "Give the date range": {"date_from": BORN, "date_to": None},
    "Which of these\nplaces": {
        "reason": "banked",
        "choice": "anywhere: the request does not tie the photos to a place",
    },
    "would be written on something": {"reason": "banked", "choices": [PRINTED.lower()]},
    "one single occasion": {"reason": "banked", "choice": "many occasions"},
    "name the main subject itself too": {"reason": "banked", "choices": []},
    "must mainly show": {"reason": "banked", "choices": ["cyclist"]},
}


def _asked(lexicon: Lexicon) -> Ask:
    view = _library()
    # WHY: stands in for the model server answering the translation's questions.
    asker = QuestionAsker(ANSWERS)
    return translate(
        REQUEST,
        view,
        household_of(view),
        lexicon,
        asker,
        today=date(2026, 9, 1),
        printed=_Printed(),
    )


def test_a_free_text_report_carries_the_trace_and_no_name_place_printed_word_or_caption(
    lexicon: Lexicon, tmp_path: Path
) -> None:
    store = open_store()
    asked = _asked(lexicon)
    film = film_for(asked, QuestionAsker(ANSWERS), events_on=lambda _day: [])
    trace = explain(asked, film=film)
    with observe_run(store, source="manual", capture_system=False) as tracker:
        record_run_attempt(tracker.run_id, tmp_path, "", store=store)
        save_with_run(asked, film, trace, people=_library().people)

    report = report_for_run(store, Config(), tracker.run_id)

    rendered = report.json() + report.markdown()
    assert "READING" in report.data["free_text"]["trace"]
    for private in (NAME, PLACE, PRINTED, CAPTION, BORN, "ride-0"):
        assert private.lower() not in rendered.lower()
    assert "the owner's son" in rendered
    assert "area A" in rendered
    assert "text-1" in rendered
