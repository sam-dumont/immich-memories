"""A film about several people names every one of them in its opening title.

`generate --memory-type multi_person --person Robin --person Kit` once opened on "Kit in 2025":
the reader dropped Robin. A multi-person film is titled by the app now, and its rules title
names the whole cast in every film language.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from immich_memories.config.loader import Config
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import template_title

THREE = ["Robin", "Kit", "Sam"]


def _no_model_title(names: list[str], locale: str) -> tuple[str, str | None]:
    return template_title(
        Config(title_screens={"locale": locale}),
        memory_type="multi_person",
        date_range=DateRange(start=datetime(2025, 1, 1), end=datetime(2025, 12, 31, 23, 59, 59)),
        person_name=None,
        preset_params={"person_names": names},
    )


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_the_no_model_title_names_all_three_people(locale):
    title, subtitle = _no_model_title(THREE, locale)

    assert title == "2025"
    assert subtitle is not None
    for name in THREE:
        assert name in subtitle
