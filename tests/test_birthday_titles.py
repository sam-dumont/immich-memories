"""A birthday film is titled by the birthday it celebrates; a birthdays film by its years."""

from datetime import datetime

import pytest

from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import template_title


@pytest.mark.parametrize("locale", ["en", "fr"])
@pytest.mark.parametrize("start_year", [2023, 2019])
def test_birthday_template_and_render_name_the_celebrated_year(tmp_path, locale, start_year):
    config = Config(title_screens={"locale": locale})
    span = DateRange(start=datetime(start_year, 2, 8), end=datetime(2024, 2, 7, 23, 59, 59))
    params = {"birthday": True, "person_names": ["Riley"]}
    title = template_title(
        config,
        memory_type="person_spotlight",
        date_range=span,
        person_name="Riley",
        preset_params=params,
    )
    assert title[0] == "2024"
    assert "Riley" in title[1]
    rendered = build_title_settings(
        GenerationParams(
            clips=[],
            output_path=tmp_path / "film.mp4",
            config=config,
            memory_type="person_spotlight",
            memory_preset_params=params,
            person_name="Riley",
            date_start=span.start.date(),
            date_end=span.end.date(),
        ),
        config,
        [],
    )
    assert (rendered.title_override, rendered.subtitle_override) == title


def test_public_birthday_command_keeps_its_annual_title_context(tmp_path):
    from tests.test_people_expression_cli import PEOPLE, Client, invoke

    class BirthdayClient(Client):
        def get_person_by_name(self, name):
            return next(person for person in PEOPLE if person.name == name)

    result, _, pipeline = invoke(
        tmp_path,
        [
            "--memory-type",
            "person_spotlight",
            "--year",
            "2024",
            "--birthday",
            "05-04",
            "--person",
            "Adult A",
            "--no-music",
            "--no-live-photos",
        ],
        BirthdayClient(),
    )
    assert result.exit_code == 0, (result.output, result.exception)
    request = pipeline.call_args.kwargs
    title, _ = template_title(
        Config(title_screens={"locale": "en"}),
        memory_type=request["memory_type"],
        date_range=request["date_range"],
        person_name="Adult A",
        preset_params=request["memory_preset_params"],
    )
    assert title == "2024"


# ── A birthday film's title names the birthday (rc.10, a birthday film titled by name alone) ──


@pytest.mark.parametrize(
    ("locale", "named"), [("en", "Riley's birthday"), ("fr", "Anniversaire de Riley")]
)
def test_the_birthday_template_names_the_birthday(locale, named):
    span = DateRange(start=datetime(2019, 2, 8), end=datetime(2024, 2, 7, 23, 59, 59))

    title = template_title(
        Config(title_screens={"locale": locale}),
        memory_type="person_spotlight",
        date_range=span,
        person_name="Riley",
        preset_params={"birthday": True, "person_names": ["Riley"]},
    )

    assert title == ("2024", named)


@pytest.mark.parametrize(("days", "years"), [((2022, 2026), "2022–2026"), ((2026,), "2026")])
def test_the_birthdays_film_renders_the_years_its_cut_shows(tmp_path, days, years):
    from types import SimpleNamespace

    config = Config(title_screens={"locale": "en"})
    params = {"birthday": True, "birthday_years_back": 5, "person_names": ["Riley"]}
    clips = [
        SimpleNamespace(
            asset=SimpleNamespace(local_taken_at=datetime(year, 2, 7, 12, 0)),
            llm_description=None,
        )
        for year in days
    ]
    rendered = build_title_settings(
        GenerationParams(
            clips=clips,
            output_path=tmp_path / "film.mp4",
            config=config,
            memory_type="person_spotlight",
            memory_preset_params=params,
            person_name="Riley",
            date_start=datetime(2021, 2, 6).date(),
            date_end=datetime(2026, 2, 8).date(),
        ),
        config,
        [],
    )

    assert (rendered.title_override, rendered.subtitle_override) == (years, "Riley's birthday")


def test_a_new_years_eve_birthdays_film_before_its_cut_names_the_celebrated_year():
    config = Config(title_screens={"locale": "en"})
    span = DateRange(start=datetime(2020, 12, 30), end=datetime(2026, 1, 1, 23, 59, 59))
    params = {"birthday": True, "birthday_years_back": 5, "person_names": ["Riley"]}

    title = template_title(
        config,
        memory_type="person_spotlight",
        date_range=span,
        person_name="Riley",
        preset_params=params,
    )

    assert title == ("2025", "Riley's birthday")
