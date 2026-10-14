"""A typed film opens on the title the app writes, and no model writes any part of it.

A birthday, a holiday, a month, a season, a year or a person's film is titled by what it is
and when ("Kit's birthday · 2026"). A model asked for a birthday's title put a day of the year
before under "birthday 2026", which read as the birthday's date. Nothing goes under the title
unless someone typed a subtitle.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import resolve_film_title


def _config(locale: str = "en", *, model: bool = True) -> Config:
    config = Config()
    config.title_screens = config.title_screens.model_copy(update={"locale": locale})
    if model:
        config.llm = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )
    return config


def _clip(day: date) -> SimpleNamespace:
    taken = datetime.combine(day, datetime.min.time())
    return SimpleNamespace(asset=SimpleNamespace(local_taken_at=taken), llm_description=None)


# memory type -> window, preset parameters, people, clips' days, English and French titles.
TYPED = {
    "year": (date(2025, 1, 1), date(2025, 12, 31), {}, (), (), "2025", "2025"),
    "season": (date(2025, 6, 1), date(2025, 8, 31), {"season": "summer", "hemisphere": "north"},
               (), (), "Summer 2025", "Été 2025"),
    "monthly_highlights": (date(2025, 7, 1), date(2025, 7, 31), {}, (), (),
                           "July 2025", "Juillet 2025"),
    "person_month": (date(2025, 7, 1), date(2025, 7, 31), {"person_names": ["Kit"]}, ("Kit",),
                     (), "Kit · July 2025", "Kit · Juillet 2025"),
    "person_spotlight": (date(2025, 1, 1), date(2025, 12, 31), {}, ("Kit",), (),
                         "Kit · 2025", "Kit · 2025"),
    "birthday": (date(2025, 8, 31), date(2026, 8, 30), {"birthday": True}, ("Kit",), (),
                 "Kit's birthday · 2026", "Anniversaire de Kit · 2026"),
    "birthdays": (date(2021, 8, 29), date(2026, 8, 31), {"birthday": True,
                  "birthday_years_back": 5}, ("Kit",), (date(2022, 8, 30), date(2026, 8, 30)),
                  "Kit's birthday · 2022–2026", "Anniversaire de Kit · 2022–2026"),
    "one_birthday_shown": (date(2021, 8, 29), date(2026, 8, 31), {"birthday": True,
                           "birthday_years_back": 5}, ("Kit",), (date(2026, 8, 30),),
                           "Kit's birthday · 2026", "Anniversaire de Kit · 2026"),
    "multi_person": (date(2025, 1, 1), date(2025, 12, 31), {"person_names": ["Kit", "Pat"]},
                     ("Kit", "Pat"), (), "Kit & Pat · 2025", "Kit & Pat · 2025"),
    "either_person": (date(2025, 1, 1), date(2025, 12, 31),
                      {"person_names": ["Kit", "Pat"], "person_match": "or"}, ("Kit", "Pat"), (),
                      "Kit & Pat · 2025", "Kit & Pat · 2025"),
    "holiday": (date(2004, 12, 23), date(2025, 12, 27), {"holiday": "christmas"}, (),
                (date(2019, 12, 25), date(2025, 12, 25)), "Christmas · 2019–2025",
                "Noël · 2019–2025"),
    "on_this_day": (date(2004, 10, 14), date(2025, 10, 14), {}, (),
                    (date(2012, 10, 14), date(2025, 10, 14)), "October 14 · 2012–2025",
                    "14 octobre · 2012–2025"),
}  # fmt: skip
_MEMORY_TYPE = {"birthday": "person_spotlight", "birthdays": "person_spotlight",
                "one_birthday_shown": "person_spotlight", "person_month": "monthly_highlights",
                "either_person": "multi_person"}  # fmt: skip


def _titled(kind: str, *, locale: str = "en", model: bool = True, enabled=None, subtitle=None):
    start, end, params, people, days, _en, _fr = TYPED[kind]
    reader = AsyncMock(return_value='{"title": "Kit in 2025", "subtitle": "13 September 2025"}')
    asked = []
    # WHY: query_llm is the reader, the one boundary a title could cross; the rest is real.
    with patch("immich_memories.titles.llm_titles.query_llm", reader):
        result = resolve_film_title(
            enabled=enabled,
            title_override=None,
            subtitle_override=subtitle,
            clips=[_clip(day) for day in days],
            config=_config(locale, model=model),
            memory_type=_MEMORY_TYPE.get(kind, kind),
            date_range=DateRange(
                start=datetime.combine(start, datetime.min.time()),
                end=datetime.combine(end, datetime.max.time()),
            ),
            person_names=list(people),
            memory_preset_params=params,
            album_lookup=lambda: asked.append("album") or "The road north",
        )
    return result, reader.call_count + len(asked)


@pytest.mark.parametrize("kind", list(TYPED))
@pytest.mark.parametrize("locale", ["en", "fr"])
@pytest.mark.parametrize("model", [True, False])
def test_a_typed_film_is_titled_by_what_it_is_and_when_and_nothing_is_asked(kind, locale, model):
    (title, subtitle, source), asked = _titled(kind, locale=locale, model=model)

    assert title == TYPED[kind][5 if locale == "en" else 6]
    assert subtitle is None
    assert source == ("occasion" if kind == "holiday" else "fallback")
    assert asked == 0


def test_llm_title_does_not_hand_a_typed_film_to_the_model():
    (title, subtitle, _source), asked = _titled("birthday", enabled=True)

    assert (title, subtitle, asked) == ("Kit's birthday · 2026", None, 0)


def test_a_typed_subtitle_stands_under_the_apps_title():
    (title, subtitle, _source), _asked = _titled("season", subtitle="By the sea")

    assert (title, subtitle) == ("Summer 2025", "By the sea")


def test_a_typed_title_still_wins_over_the_apps_own():
    result = resolve_film_title(
        enabled=None,
        title_override="Our summer",
        subtitle_override="By the sea",
        clips=[],
        config=_config(model=False),
        memory_type="season",
        date_range=DateRange(datetime(2025, 6, 1), datetime(2025, 8, 31, 23, 59)),
        person_names=[],
        memory_preset_params={"season": "summer", "hemisphere": "north"},
    )

    assert result[:2] == ("Our summer", "By the sea")
