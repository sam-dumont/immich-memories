"""A French day's title survives the title guard, and a day's title is written from its facts (#2667).

On a French catalogue the guard dropped every possessive title: "Anniversaire de Kit" read as a
claim that the day was in a place called Kit. Its word lists were English, so "Noël" and "Dimanche"
were inventions too. And the day question's own titles were generic ("The Gathering") or English;
a title written from a short list of the day's facts named the occasion and the person instead.
Every name and place below is made up.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from immich_memories.analysis.special_days.facts_title import (
    TITLE_VERSION,
    DayFacts,
    facts_text,
    title_prompt,
)
from immich_memories.analysis.special_days.title import title_the_day_can_keep
from immich_memories.automation.special_day_scan import scan_year
from immich_memories.config.models.llm import LLMConfig
from tests.picture_fake import PictureFake

_DAY = date(2022, 5, 14)
_BORN = date(2022, 6, 2)


def _picture(
    when: date,
    hour: int,
    *,
    city: str | None = "Anytown",
    people: tuple[str, ...] = ("Kit Example",),
    minute: int = 0,
) -> PictureFake:
    located = city is not None
    return PictureFake(
        id=f"p-{when:%m%d}-{hour:02d}-{minute:02d}",
        file_created_at=datetime(when.year, when.month, when.day, hour, minute, tzinfo=UTC),
        exif_info=SimpleNamespace(
            city=city,
            state=None,
            country="Belgium" if located else None,
            latitude=50.8 if located else None,
            longitude=4.4 if located else None,
        ),
        people=[SimpleNamespace(name=name, id=name.split()[0].lower()) for name in people],
        is_favorite=False,
        is_video=False,
        duration_seconds=None,
        llm_description="children around a table with a cake",
    )


def _day(when: date = _DAY, **kwargs) -> list:
    return [_picture(when, hour, minute=m, **kwargs) for hour in range(10, 18) for m in (0, 30)]


def _keep(title: str, day: list, locale: str = "fr") -> str:
    return title_the_day_can_keep(title, day, evidence="", locale=locale)


class TestAPersonIsNotAPlace:
    @pytest.mark.parametrize("title", ["Anniversaire de Kit", "Le voyage de Kit"])
    def test_a_title_about_someone_on_the_days_pictures_is_kept(self, title: str) -> None:
        assert _keep(title, _day()) == title

    def test_an_invented_place_after_de_is_still_refused(self) -> None:
        """The check "de" was put there for: a circuit the day never went to."""
        assert _keep("Circuit de Farplace", _day()) == ""

    def test_a_name_nobody_on_the_pictures_carries_is_still_read_as_a_place(self) -> None:
        assert _keep("Anniversaire de Remy", _day()) == ""

    def test_a_place_after_a_french_preposition_is_checked(self) -> None:
        assert _keep("Week-end à Farplace", _day()) == ""
        assert _keep("Week-end à Anytown", _day()) == "Week-end à Anytown"


class TestTheInstallsCalendarWords:
    @pytest.mark.parametrize("title", ["Le réveillon de Noël", "Fête de Pâques en famille"])
    def test_a_public_holiday_in_the_installs_language_is_not_a_place(self, title: str) -> None:
        assert _keep(title, _day()) == title

    def test_a_weekday_in_the_installs_language_names_nothing(self) -> None:
        unplaced = _day(city=None, people=())

        assert _keep("Promenade du Dimanche", unplaced) == "Promenade du Dimanche"

    def test_a_feast_that_is_not_a_public_holiday_still_needs_the_day_to_name_it(self) -> None:
        unplaced = _day(city=None, people=())

        assert _keep("Fête de la Saint-Nicolas", unplaced) == ""

    @pytest.mark.parametrize("title", ["Lundi 13 août", "Samedi 2 mars 2024"])
    def test_a_date_in_the_installs_language_is_not_a_title(self, title: str) -> None:
        assert _keep(title, _day()) == ""


class TestEnglishTitlesAsBefore:
    def test_a_date_is_not_a_title(self) -> None:
        assert _keep("Monday 13 August 2007", _day(), locale="en") == ""

    def test_a_verb_after_to_is_not_a_place(self) -> None:
        assert _keep("A Day to Remember", _day(), locale="en") == "A Day to Remember"

    def test_an_invented_place_is_refused(self) -> None:
        assert _keep("A day in Farplace", _day(), locale="en") == ""
        assert _keep("A day in Anytown", _day(), locale="en") == "A day in Anytown"

    def test_a_french_holiday_is_not_an_english_word(self) -> None:
        assert _keep("Le réveillon de Noël", _day(), locale="en") == ""


def _facts(**changes) -> DayFacts:
    facts = DayFacts(
        pictures=42,
        hours=6,
        near_home=True,
        towns=Counter({"Anytown": 40, "Someplace": 2}),
        who=Counter({"Kit Example": 30, "Pat Example": 12}),
        role_of={"Kit Example": "daughter"},
        born=(),
        birthday=("Kit Example",),
        holiday="",
        acts=Counter({"celebration": 9, "eating-drinking": 4, "posing": 20}),
        said=("children around a table with a cake", "a garden with balloons"),
    )
    return DayFacts(**{**facts.__dict__, **changes})


class TestTheFactsList:
    def test_the_facts_say_the_day_who_the_occasion_and_what_it_showed(self) -> None:
        assert facts_text(_facts()) == "\n".join(
            [
                "THE DAY: 42 pictures over 6 hours, at home.",
                "WHERE: Anytown; Someplace",
                "WHO, on the most pictures: Kit (daughter); Pat",
                "THE OCCASION: the birthday of Kit",
                "WHAT THE PICTURES SHOW: a celebration (9), a meal (4)",
                "SOME OF THEM, in order:",
                "- children around a table with a cake",
                "- a garden with balloons",
            ]
        )

    def test_a_crowd_is_counted_and_an_unplaced_day_says_so(self) -> None:
        who = Counter({f"Person{n} Example": 10 - n for n in range(6)})
        text = facts_text(
            _facts(who=who, role_of={}, near_home=None, towns=Counter(), birthday=(), said=())
        )

        assert "THE DAY: 42 pictures over 6 hours, place not recorded." in text
        assert "WHO, on the most pictures: Person0; Person1; Person2; Person3; and 2 others" in text
        assert "WHERE" not in text and "OCCASION" not in text and "SOME OF THEM" not in text

    def test_the_prompt_carries_its_version_the_facts_and_the_language(self) -> None:
        prompt = title_prompt(_facts(), "fr")

        first, *rest = prompt.splitlines()
        assert first.endswith(TITLE_VERSION)
        assert facts_text(_facts()) in prompt
        assert "Write its title in French, at most 6 words" in prompt
        assert prompt.rstrip().endswith('JSON only: {"title":"..."}')


class _Reader:
    """The text model: the day question calls the day an occasion with a generic English
    title; the facts title prompt gets `title`."""

    # WHY: the text model is the one external boundary; it records what it was asked.
    def __init__(self, title: str = "Anniversaire de Kit") -> None:
        self.title = title
        self.prompts: list[str] = []

    def __call__(self, prompt: str, *_args, **_kwargs) -> str:
        self.prompts.append(prompt)
        if TITLE_VERSION in prompt:
            return json.dumps({"title": self.title})
        return json.dumps(
            {"special": True, "title": "The Gathering", "subtitle": "", "what": "a party"}
        )

    @property
    def title_prompts(self) -> list[str]:
        return [p for p in self.prompts if TITLE_VERSION in p]


def _scanned(reader, monkeypatch, *, library: list | None = None, **kwargs) -> dict:
    # WHY: the month reading is a model call; it proposes the one run of the library.
    monkeypatch.setattr(
        "immich_memories.analysis.special_days.sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R1", "what": "a party"}]}),
    )
    # WHY: the day question and the title question go to the text model; `reader` answers both.
    with (
        patch("immich_memories.analysis.special_days.detection._ask", side_effect=reader),
        patch("immich_memories.analysis.special_days.facts_title._ask", side_effect=reader),
    ):
        found = scan_year(
            library or _day(), llm_config=LLMConfig(), home=None, locale="fr", **kwargs
        )
    return {entry.day: entry.title for entry in found}


class TestTheScanTitlesFromTheFacts:
    def test_the_days_title_is_written_from_its_facts(self, monkeypatch) -> None:
        reader = _Reader()
        day = _day()

        titles = _scanned(
            reader,
            monkeypatch,
            library=day,
            close_family={"kit": "daughter"},
            activities={p.id: "celebration" for p in day},
            captions={day[0].id: "a cake with six candles"},
        )

        assert titles == {_DAY: "Anniversaire de Kit"}
        prompt = reader.title_prompts[0]
        assert "THE DAY: 16 pictures over 8 hours, place not recorded." in prompt
        assert "WHERE: Anytown" in prompt
        assert "WHO, on the most pictures: Kit (daughter)" in prompt
        assert "WHAT THE PICTURES SHOW: a celebration (16)" in prompt
        assert "SOME OF THEM, in order:\n- a cake with six candles" in prompt

    def test_a_birthday_from_the_registry_is_among_the_facts(self, monkeypatch) -> None:
        reader = _Reader()

        _scanned(reader, monkeypatch, births={date(2015, 5, 14): ("Kit",)})

        assert "THE OCCASION: the birthday of Kit" in reader.title_prompts[0]

    def test_the_written_title_goes_through_the_guard(self, monkeypatch) -> None:
        """An invented place is refused, and the day's own place names it instead."""
        titles = _scanned(_Reader("Fête à Farplace"), monkeypatch)

        assert titles == {_DAY: "Une journée à Anytown"}

    def test_a_birth_day_keeps_its_birth_title(self, monkeypatch) -> None:
        reader = _Reader()
        library = _day(_BORN)

        titles = _scanned(reader, monkeypatch, library=library, births={_BORN: ("Kit",)})

        assert titles == {_BORN: "Naissance de Kit"}
        assert reader.title_prompts == []

    def test_no_answer_keeps_the_day_questions_title(self, monkeypatch) -> None:
        def reader(prompt: str, *_args, **_kwargs) -> str:
            if TITLE_VERSION in prompt:
                raise TimeoutError("the reader is away")
            return json.dumps(
                {"special": True, "title": "Une fête au jardin", "subtitle": "", "what": "a party"}
            )

        assert _scanned(reader, monkeypatch) == {_DAY: "Une fête au jardin"}

    def test_without_a_model_the_title_is_the_days_place(self) -> None:
        starred = [PictureFake(**{**p.__dict__, "is_favorite": True}) for p in _day()]

        found = scan_year(starred, llm_config=None, home=None, reader="rules", locale="fr")

        assert [entry.title for entry in found] == ["Une journée à Anytown"]


class TestTheActivityHeadsReachTheScan:
    def test_the_banked_activity_of_each_picture_is_read_from_the_store(self) -> None:
        from immich_memories.cache.embedding_cache import HeadFactStore
        from immich_memories.cli.special_days_cmd import _activities
        from immich_memories.config.loader import Config
        from immich_memories.triage.heads import HeadFact
        from tests.annotation_rows import annotation_store

        store = annotation_store()
        config = Config()
        version = config.editorial.active_head_versions["activity"]
        HeadFactStore(store).remember_facts(
            {
                "p-1": [HeadFact("activity", "celebration", 0.9, version)],
                "p-2": [HeadFact("activity", "playing", 0.8, "an-older-head")],
            },
            encoder_key="test-encoder",
        )
        pictures = [SimpleNamespace(id="p-1"), SimpleNamespace(id="p-2")]

        assert _activities(pictures, store, config) == {"p-1": "celebration"}
        assert _activities(pictures, None, config) == {}
