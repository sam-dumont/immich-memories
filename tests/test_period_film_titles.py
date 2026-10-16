"""A film's title names its own subject: a period by the period, a special day by its stories.

The demo library's month (tests/e2e/fake_library.py) is the answer key: a summer that turns
around Kit's birthday and then drives north. Its season film was titled "The road north,
2025" after the trip album, and its special day got no title at all. Model replies are
canned at the reader boundary and go through the real prompt, parsing and guard chain.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from immich_memories.config.loader import Config
from immich_memories.config.models.llm import LLMConfig
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_stories import (
    FilmStories,
    film_stories_from_plan,
    read_film_stories,
)
from immich_memories.titles.film_title import resolve_film_title, template_title
from immich_memories.titles.text_builder import SelectionType, generate_title
from tests.e2e.fake_library import STORIES, THESIS, TRIP_DAYS

ALBUM = "The road north"

# The four stories as the planner records them after #2486: name, weight, and the new keys.
_STORY_FACTS = {
    "S0001": {"occasion": "birthday", "people": ["Kit", "Pat", "Lou"], "places": ["Brussels"],
              "days": ["2025-07-05", "2025-07-05"]},
    "S0002": {"occasion": "trip", "people": ["Robin", "Charlie", "Kit"],
              "places": ["Nordkapp", "Lofoten"], "days": list(TRIP_DAYS)},
    "S0003": {"occasion": "event", "people": ["Kit", "Pat"], "places": ["Brussels"],
              "days": ["2025-07-06", "2025-07-06"]},
    "S0004": {"occasion": None, "people": [], "places": ["Brussels"],
              "days": ["2025-07-01", "2025-07-10"]},
}  # fmt: skip


def _episode(story) -> dict:
    return {
        "episode": story.key,
        "title": story.title,
        "weight": story.weight,
        "purpose": story.purpose,
        "granted": 3,
        "trip": None,
        **_STORY_FACTS[story.key],
    }


def _plan(*, summary: str | None = THESIS, extra: tuple[dict, ...] = ()) -> dict:
    episodes = [*(_episode(s) for s in STORIES), *extra]
    return {"story": {"thesis": summary or "", "episodes": episodes}}


def _stories() -> FilmStories:
    return film_stories_from_plan(_plan())


def _config(locale: str = "en", *, model: bool = True) -> Config:
    config = Config()
    config.title_screens = config.title_screens.model_copy(update={"locale": locale})
    if model:
        config.title_screens.llm_titles = True  # model-written titles are opt-in
        config.llm = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )
    return config


# memory type, its window, its preset parameters, and the period it is titled by (English).
PERIODS = {
    "season": (date(2025, 6, 1), date(2025, 8, 31), {"season": "summer", "hemisphere": "north"},
               "Summer 2025"),
    "year_in_review": (date(2025, 1, 1), date(2025, 12, 31), {}, "2025"),
    "year": (date(2025, 1, 1), date(2025, 12, 31), {}, "2025"),
    "monthly_highlights": (date(2025, 7, 1), date(2025, 7, 31), {}, "July 2025"),
}  # fmt: skip


def _window(start: date, end: date) -> DateRange:
    return DateRange(start=datetime.combine(start, datetime.min.time()),
                     end=datetime.combine(end, datetime.max.time()))  # fmt: skip


def _titled(
    reply: str,
    memory_type: str,
    *,
    locale: str = "en",
    stories: FilmStories | None = None,
    person_names: tuple[str, ...] = (),
    clips: tuple = (),
    window: tuple[date, date] | None = None,
    preset: dict | None = None,
    album: str | None = ALBUM,
    model: bool = True,
):
    start, end, params, _period = PERIODS.get(memory_type, (None, None, {}, None))
    if window is not None:
        start, end = window
    reader = AsyncMock(return_value=reply)
    # WHY: query_llm is the reader, the one boundary a title crosses; the rest is real.
    with patch("immich_memories.titles.llm_titles.query_llm", reader):
        result = resolve_film_title(
            enabled=None,
            title_override=None,
            clips=list(clips),
            config=_config(locale, model=model),
            memory_type=memory_type,
            date_range=_window(start, end),
            person_names=list(person_names),
            memory_preset_params=params | (preset or {}),
            album_lookup=lambda: album,
            stories=stories,
        )
    prompt = reader.call_args.args[0] if reader.call_args else ""
    return result, prompt


def _season_name(locale: str) -> str:
    return generate_title(
        SelectionType.SEASON, season="summer", year=2025, locale=locale
    ).main_title


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_a_season_is_titled_by_its_season_in_every_film_language(locale):
    (title, subtitle, _source), prompt = _titled(
        '{"title": "The road north, 2025", "subtitle": null}',
        "season",
        locale=locale,
        stories=_stories(),
    )

    assert (title, subtitle, prompt) == (_season_name(locale), None, "")


@pytest.mark.parametrize("memory_type", list(PERIODS))
def test_with_no_model_the_title_is_the_period_and_nothing_is_asked(memory_type):
    start, end, params, period = PERIODS[memory_type]
    (title, subtitle, source), prompt = _titled(
        '{"title": "unused", "subtitle": null}', memory_type, model=False
    )

    assert (title, subtitle, source, prompt) == (period, None, "fallback", "")
    rules = template_title(
        _config(model=False),
        memory_type=memory_type,
        date_range=_window(start, end),
        person_name=None,
        preset_params=params,
    )
    assert rules[0] == period


def test_a_season_with_no_home_base_still_names_its_season_on_the_title_card(tmp_path):
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_settings import build_title_settings

    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=_config(model=False),
        memory_type="season",
        memory_preset_params={"season": "summer", "hemisphere": "south"},
        date_start=date(2024, 12, 1),
        date_end=date(2025, 2, 28),
    )

    settings = build_title_settings(params, params.config, [])

    assert settings is not None
    assert settings.hemisphere == "south"


def test_the_stories_are_read_heaviest_first_and_a_trips_legs_fold_into_it():
    legs = (
        {"episode": "S9", "title": "Lofoten", "weight": "minor", "trip": "The road north",
         "places": ["Reine"], "days": ["2025-07-20", "2025-07-22"], "granted": 2},
        {"episode": "S10", "title": "posing / playing at Ixelles", "weight": "major",
         "granted": 4},
        {"episode": "S11", "title": "2025-07-10", "weight": "minor", "granted": 1},
        {"episode": "S12", "title": "Left on the floor", "weight": "none", "granted": 0},
    )  # fmt: skip

    stories = film_stories_from_plan(_plan(extra=legs))

    names = [story.name for story in stories.stories]
    assert names == ["Kit's birthday", "The road north", "A Sunday in the forest", "Ordinary days"]
    trip = stories.stories[1]
    assert trip.weight == "major"
    assert "Reine" in trip.places
    assert stories.summary == THESIS


def test_an_attempt_with_no_plan_tells_the_title_no_stories(tmp_path):
    assert read_film_stories(tmp_path) == FilmStories()
    assert read_film_stories(None) == FilmStories()


def _picture(day: str, city: str, people: tuple[str, ...]):
    taken = datetime.fromisoformat(f"{day}T15:00:00")
    asset = SimpleNamespace(
        exif_info=SimpleNamespace(city=city, state=None, country="Belgium", place_name=None),
        local_taken_at=taken,
        people=[SimpleNamespace(name=name) for name in people],
    )
    return SimpleNamespace(asset=asset, llm_description=None)


_PARTY = (
    _picture("2025-07-05", "Ixelles", ("Kit", "Pat")),
    _picture("2025-07-05", "Ixelles", ("Kit", "Lou")),
    _picture("2025-07-05", "Ixelles", ("Kit",)),
)
_PARTY_DAY = (date(2025, 7, 5), date(2025, 7, 5))


def test_an_uncatalogued_special_day_is_named_from_its_stories_and_pictures():
    (title, subtitle, source), prompt = _titled(
        '{"title": "Kit\'s birthday", "subtitle": "5 July 2025"}',
        "special_day",
        stories=film_stories_from_plan(_plan(summary="Kit turns one at home.")),
        clips=_PARTY,
        window=_PARTY_DAY,
        album=None,
    )

    assert (title, subtitle, source) == ("Kit's birthday", "5 July 2025", "model")
    assert "2025-07-05: Ixelles, Belgium" in prompt
    assert "Kit" in prompt.split("People most present in the pictures", 1)[1]


def test_an_uncatalogued_special_day_with_no_model_is_named_after_its_place():
    (title, subtitle, source), _prompt = _titled(
        '{"title": "unused", "subtitle": null}',
        "special_day",
        clips=_PARTY,
        window=_PARTY_DAY,
        model=False,
    )

    assert (title, subtitle, source) == ("A day in Ixelles", "5 July 2025", "fallback")
