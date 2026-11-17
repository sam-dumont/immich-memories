"""A special day is titled in the install's language, and a birth date makes the day a birth (#2667).

A French install's catalogue came back titled in English: the day question carried no language,
and the fallback title was an English template. A child's birth day came back titled after the
district it happened in, though the people registry holds the child's birth date. Every name and
place below is made up.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from immich_memories.analysis.special_days.detection import ask_if_special
from immich_memories.analysis.special_days.sequence import close_family_births
from immich_memories.analysis.special_days.title import honest_title, retitle_prompt
from immich_memories.automation.catalogue import (
    entries_from,
    load_catalogue,
    record_for,
    save_catalogue,
)
from immich_memories.automation.special_day_scan import DiscoveredDay, scan_year
from immich_memories.cli.generate_resolution import resolve_special_day
from immich_memories.config.loader import Config
from immich_memories.people.context import load_people_prompt_context
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import resolve_film_title
from tests.people_registry_seed import seed_people
from tests.picture_fake import PictureFake

_BORN = date(2021, 7, 3)
_OTHER = date(2021, 7, 14)


def _day(when: date, *, city: str = "Anytown", hours: range = range(9, 17)) -> list:
    return [
        PictureFake(
            id=f"p-{when:%m%d}-{hour}",
            file_created_at=datetime(when.year, when.month, when.day, hour, tzinfo=UTC),
            exif_info=SimpleNamespace(
                city=city, state=None, country="Belgium", latitude=50.8, longitude=4.4
            ),
            people=[],
            is_favorite=False,
            is_video=False,
            duration_seconds=None,
            llm_description="a family in a bright room",
        )
        for hour in hours
    ]


class _Reader:
    """The day question's text model, answering every day as an occasion."""

    # WHY: the text model is the one external boundary; it records what it was asked.
    def __init__(self, title: str = "Une journée à la maison") -> None:
        self.prompts: list[str] = []
        self.title = title

    def __call__(self, prompt: str, *_args, **_kwargs) -> str:
        self.prompts.append(prompt)
        return json.dumps({"special": True, "title": self.title, "subtitle": "", "what": "a day"})


def _asked(reader: _Reader):
    # WHY: the day question's text model is the boundary; `reader` answers in its place.
    return patch("immich_memories.analysis.special_days.detection._ask", side_effect=reader)


class TestTheLanguage:
    def test_a_french_installs_day_question_asks_for_french(self) -> None:
        reader = _Reader()
        with _asked(reader):
            ask_if_special(_day(_OTHER), llm_config=SimpleNamespace(), locale="fr")

        assert "in French" in reader.prompts[0]

    def test_a_prepared_days_question_asks_for_the_language_too(self) -> None:
        """The caption route asks its own question; it carries the language as well."""
        day = _day(_OTHER, hours=range(8, 22))
        captions = {p.id: "a family in a bright room" for p in day}
        reader = _Reader()
        with _asked(reader):
            ask_if_special(day, llm_config=SimpleNamespace(), captions=captions, locale="de")

        assert "in German" in reader.prompts[0]

    def test_a_second_title_is_asked_for_in_the_language(self) -> None:
        prompt = retitle_prompt("lines", rejected="Somewhere", assets=[], locale="es")

        assert "in Spanish" in prompt

    def test_the_place_title_comes_from_the_catalogue(self) -> None:
        """The plain place title once was English on every install."""
        day = _day(_OTHER)

        assert honest_title(day, what="a day", evidence="", locale="fr") == "Une journée à Anytown"
        assert honest_title(day, what="a day", evidence="", locale="en") == "A day in Anytown"


class TestABirthDate:
    def test_the_day_someone_was_born_is_their_birth(self) -> None:
        reader = _Reader()
        with _asked(reader):
            verdict = ask_if_special(
                _day(_BORN), llm_config=SimpleNamespace(), locale="fr", born=("Kit",)
            )

        assert verdict.special is True
        assert verdict.title == "Naissance de Kit"
        assert "Kit" in reader.prompts[0], "the day's facts say whose birth it was"

    def test_the_birth_wording_follows_each_language(self) -> None:
        with _asked(_Reader()):
            english = ask_if_special(
                _day(_BORN), llm_config=SimpleNamespace(), locale="en", born=("Anne",)
            )
        with _asked(_Reader()):
            french = ask_if_special(
                _day(_BORN), llm_config=SimpleNamespace(), locale="fr", born=("Anne",)
            )

        assert english.title == "The birth of Anne"
        assert french.title == "Naissance d'Anne"

    def test_a_birth_is_kept_even_when_the_reader_calls_the_day_ordinary(self) -> None:
        # WHY: the text model is the boundary; this one finds nothing in the day.
        with patch(
            "immich_memories.analysis.special_days.detection._ask",
            return_value='{"special": false}',
        ):
            verdict = ask_if_special(
                _day(_BORN), llm_config=SimpleNamespace(), locale="fr", born=("Kit",)
            )

        assert (verdict.special, verdict.title) == (True, "Naissance de Kit")

    def test_a_day_nobody_was_born_on_keeps_its_own_title(self) -> None:
        reader = _Reader(title="Une fête au jardin")
        with _asked(reader):
            verdict = ask_if_special(_day(_OTHER), llm_config=SimpleNamespace(), locale="fr")

        assert verdict.title == "Une fête au jardin"
        assert "born" not in reader.prompts[0].split("Answer with STRICT JSON only")[1]

    def test_close_family_birth_dates_come_from_the_people_registry(self) -> None:
        store = seed_people(
            yaml.safe_dump(
                {
                    "owner": {"person_id": "owner", "name": "Sam Example", "identified": "account"},
                    "people": [
                        {"ids": ["owner"], "name": "Sam Example", "birth_date": "1980-02-02"},
                        {
                            "ids": ["kit"],
                            "name": "Kit",
                            "birth_date": _BORN.isoformat(),
                            "confirmed": {"role": "daughter", "links": []},
                        },
                        {
                            "ids": ["pat"],
                            "name": "Pat",
                            "birth_date": "2021-07-04",
                            "confirmed": {"role": "friend", "links": []},
                        },
                        {"ids": ["lou"], "name": "Lou", "confirmed": {"role": "son"}},
                    ],
                },
                sort_keys=False,
            )
        )

        births = close_family_births(load_people_prompt_context(store))

        assert births == {_BORN: ("Kit",), date(1980, 2, 2): ("Sam Example",)}


def _library() -> list:
    """A birth day at home and a busy day away, three weeks into a year of quiet days."""
    return _day(_BORN, city="Someplace") + _day(_OTHER, city="Faraway")


class TestTheScan:
    def test_without_a_model_a_birth_day_is_found_and_named_in_the_language(self) -> None:
        found = scan_year(
            _library(),
            llm_config=None,
            home=None,
            reader="rules",
            locale="fr",
            births={_BORN: ("Kit",)},
        )

        titles = {entry.day: entry.title for entry in found}
        assert titles[_BORN] == "Naissance de Kit"
        assert all(entry.locale == "fr" for entry in found)

    def test_with_a_model_the_birth_day_is_asked_with_its_fact(self, monkeypatch) -> None:
        # WHY: the month reading is a model call; it proposes no day, so only the birth does.
        monkeypatch.setattr(
            "immich_memories.analysis.special_days.sequence._read",
            lambda *_a, **_k: '{"occasions": []}',
        )
        reader = _Reader()
        with _asked(reader):
            found = scan_year(
                _library(),
                llm_config=None,
                home=None,
                locale="fr",
                births={_BORN: ("Kit",)},
            )

        assert [(entry.day, entry.title) for entry in found] == [(_BORN, "Naissance de Kit")]
        assert len(reader.prompts) == 1 and "Kit" in reader.prompts[0]


class TestTheFilmTitle:
    _RANGE = DateRange(start=datetime(2021, 7, 3), end=datetime(2021, 7, 3, 23, 59))

    def _title(self, locale: str, params: dict) -> tuple:
        return resolve_film_title(
            enabled=None,
            title_override=params["title"],
            subtitle_override=params["subtitle"],
            clips=[],
            config=Config(tier="basic", title_screens={"locale": locale}),
            memory_type="special_day",
            date_range=self._RANGE,
            person_names=[],
            memory_preset_params=params,
            ask=lambda **_kwargs: None,
        )

    def test_a_row_written_in_the_films_language_is_its_title(self) -> None:
        params = {"title": "Naissance de Kit", "subtitle": "", "title_locale": "fr"}

        title, _subtitle, source = self._title("fr", params)

        assert title == "Naissance de Kit"
        assert source is not None and source.value == "occasion"

    def test_a_row_in_another_language_is_not_shown_verbatim(self) -> None:
        params = {"title": "Naissance de Kit", "subtitle": "", "title_locale": "fr"}

        title, _subtitle, _source = self._title("en", params)

        assert title != "Naissance de Kit"

    def test_the_rows_language_travels_from_the_catalogue_to_the_film(self) -> None:
        row = DiscoveredDay(
            day=_BORN,
            title="Naissance de Kit",
            subtitle="",
            what="the day Kit was born",
            photos=8,
            window=None,
            run_start=datetime(2021, 7, 3, 9, tzinfo=UTC),
            run_end=datetime(2021, 7, 3, 16, tzinfo=UTC) + timedelta(minutes=1),
            locale="fr",
        )
        save_catalogue([record_for(row)])

        assert entries_from(load_catalogue())[0].locale == "fr"
        params = resolve_special_day(_BORN, "special_day")
        assert params is not None and params["title_locale"] == "fr"
