"""The evaluation set as recorded fixtures: each prompt translated end to end, with no model.

One JSON file per prompt in `prompts/`: the request, the model's banked answers (keyed by a
phrase of the question they answer), and what the translation must come to. Adding a prompt
is adding a file. Every prompt runs against the same synthetic household (`eval_library`),
and every name, place and caption in it is invented.

Expectations, each optional: `reading` (the agreed parts), `who` (`present`, `anchors`,
`company`), `when` ([start, end]), `where` (the scope), `subject` (the main words), `facts`
(the library fields linked), `funnel` (the step names), `pool` (exactly these groups of the library, or asset ids),
`verdict`, `film` (the handoff's route).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from immich_memories.free_text.handoff import film_for
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.reading import PARTS
from immich_memories.free_text.translate import Ask, household_of, translate
from tests.free_text.banked import recorded
from tests.free_text.eval_library import GROUPS, HOME, group, household_library

PROMPTS = sorted((Path(__file__).parent / "prompts").glob("*.json"))


class _Printed:
    # WHY: stands in for Immich's OCR search, a read of the server's text index.
    def __init__(self, found: dict[str, list[str]]) -> None:
        self.found = found

    def pictures_reading(self, text: str) -> frozenset[str]:
        return frozenset(self.found.get(text, ()))


def _translated(fixture: dict[str, Any], lexicon: Lexicon) -> tuple[Ask, str]:
    view = household_library()
    # WHY: stands in for the model server: its answers were recorded with the fixture.
    asker = recorded(fixture["answers"])
    asked = translate(
        fixture["request"],
        view,
        household_of(view, home_base=HOME),
        lexicon,
        asker,
        today=date.fromisoformat(fixture.get("today", "2026-09-01")),
        printed=_Printed(fixture.get("printed", {})),
    )
    film = film_for(asked, asker, events_on=lambda _day: [])
    return asked, film.route


def _came_to(asked: Ask, route: str) -> dict[str, Any]:
    translation, pool = asked.translation, asked.pool
    return {
        "reading": {
            part: list(getattr(translation.reading, part))
            for part in PARTS
            if getattr(translation.reading, part)
        },
        "who": {
            "present": list(translation.who.present),
            "anchors": list(translation.who.anchors),
            "company": translation.who.company,
        },
        "when": [
            str(bound) if bound else None
            for bound in (translation.when.start, translation.when.end)
        ],
        "where": translation.where.scope,
        "subject": list(translation.subject.main),
        "facts": {
            "places": [list(place) for place in translation.facts.places],
            "picture_kinds": list(translation.facts.picture_kinds),
            "sharpness": translation.facts.sharpness,
            "people": list(translation.facts.people),
            "extreme": translation.facts.extreme,
        },
        "funnel": [step.name for step in pool.funnel],
        "pool": {picture.asset_id for picture in pool.pictures},
        "verdict": pool.verdict,
        "film": route,
    }


def _ids(name: str) -> set[str]:
    return group(name) if name in GROUPS else {name}


@pytest.mark.parametrize("path", PROMPTS, ids=[path.stem for path in PROMPTS])
def test_a_recorded_prompt_translates_as_expected(path: Path, lexicon: Lexicon) -> None:
    fixture = json.loads(path.read_text())
    expected = fixture["expect"]

    came = _came_to(*_translated(fixture, lexicon))

    if "pool" in expected:
        expected = {**expected, "pool": set().union(*map(_ids, expected["pool"]))}
    for field in ("who", "facts"):
        if field in expected:
            came[field] = {key: came[field][key] for key in expected[field]}
    assert {field: came[field] for field in expected} == expected


def test_the_evaluation_set_holds_the_dev_and_held_out_shapes() -> None:
    assert len(PROMPTS) >= 12
