"""A people film nobody dated is titled by the years its cut shows, not by a birth date."""

from datetime import date
from pathlib import Path

import pytest

from immich_memories.api.models import Person
from immich_memories.api.person_expression import PersonExpression
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.people.expression_window import library_people_window
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.titles.film_title import static_title

PEOPLE = [
    Person(id="m", name="Mira Example", birthDate="1988-01-22"),
    Person(id="t", name="Tomas Example", birthDate="1990-06-03"),
]


def _dateless(expression: PersonExpression):
    """The window and the run record `generate` writes when no dates were typed."""
    window = library_people_window(expression, read_people=lambda: PEOPLE, today=date(2026, 10, 17))
    assert window is not None
    names = list(expression.leaf_values)
    return window.range, {"person_names": names, "window_origin": window.origin}


def _shot_in(*years: int) -> list[AssemblyClip]:
    return [
        AssemblyClip(path=Path(f"{year}.mp4"), duration=3.0, date=f"{year}-05-01T10:00:00")
        for year in years
    ]


CASES = [
    ("person_spotlight", PersonExpression("person", "Mira Example"), "Mira"),
    (
        "multi_person",
        PersonExpression(
            "all",
            children=(
                PersonExpression("person", "Mira Example"),
                PersonExpression("person", "Tomas Example"),
            ),
        ),
        "Mira & Tomas",
    ),
]


@pytest.mark.parametrize("locale", ["en", "fr"])
@pytest.mark.parametrize(("memory_type", "expression", "name"), CASES)
def test_a_dateless_people_film_names_the_years_its_pictures_cover(
    tmp_path, locale, memory_type, expression, name
):
    config = Config(title_screens={"locale": locale})
    span, params = _dateless(expression)
    if memory_type == "multi_person":
        params["person_expression"] = expression.to_dict()

    title = static_title(
        config,
        memory_type=memory_type,
        date_range=span,
        person_name="Mira Example",
        preset_params=params,
        years={2003, 2011, 2026},
    )
    assert title == f"{name} · 2003–2026"

    rendered = build_title_settings(
        GenerationParams(
            clips=[],
            output_path=tmp_path / "film.mp4",
            config=config,
            memory_type=memory_type,
            memory_preset_params=params,
            person_name="Mira Example",
            date_start=span.start.date(),
            date_end=span.end.date(),
        ),
        config,
        _shot_in(2003, 2011, 2026),
    )
    assert rendered is not None
    assert rendered.title_override == "2003–2026"
    assert " · ".join(filter(None, (rendered.subtitle_override, "2003–2026"))) == title


def test_a_person_film_with_typed_dates_keeps_the_dates_it_was_asked_for(tmp_path):
    from immich_memories.timeperiod import custom_range

    config = Config(title_screens={"locale": "en"})
    span = custom_range(date(2019, 3, 1), date(2026, 10, 15))
    title = static_title(
        config,
        memory_type="person_spotlight",
        date_range=span,
        person_name="Mira Example",
        preset_params={"person_names": ["Mira Example"]},
        years={2020, 2026},
    )
    assert "March 2019" in title
