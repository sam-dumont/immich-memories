"""A film in another language says everything in that language (#2512, #2394).

Through the production Basic editor (`real_editor.py`), with `title_screens.locale: fr`: every
story's name and purpose, the film's summary and the title a birthday film carries come from
the French catalogue. The check is the English catalogue's own words, with the English months
and weekdays: none may be left once the household's names and its album's name (data, not
language) are taken out. Place names are Immich's and are never catalogue words.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from babel.dates import get_day_names, get_month_names

from immich_memories.i18n import film_texts
from tests.e2e.fake_immich import ALBUMS, FakeImmichServer
from tests.e2e.fake_library import CAST, household_people
from tests.features.cli_harness import OutboundTrap, UserHome
from tests.integration.features.real_editor import EditedFilm, generate, home_on

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fake_immich_only("reads the plan's stories and the cut's titles"),
]

_RENDER = ("--include-photos", "--no-music", "--quiet")
_WORD = re.compile(r"[^\W\d_]{3,}")
# Names a film shows as they are in any language: the household and its album.
_NAMES = sorted({*CAST, *(album["albumName"] for album in ALBUMS)}, key=len, reverse=True)


def _words(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(re.sub(r"\{[^}]*\}", " ", text))}


def _vocabulary(locale: str) -> set[str]:
    words = {w for forms in film_texts(locale).values() for form in forms for w in _words(form)}
    words |= _words(" ".join(get_month_names("wide", locale=locale).values()))
    return words | _words(" ".join(get_day_names("wide", locale=locale).values()))


def _left_in_english(text: str) -> set[str]:
    for name in _NAMES:
        text = text.replace(name, " ")
    return _words(text) & (_vocabulary("en") - _vocabulary("fr"))


def _told(film: EditedFilm) -> dict[str, str]:
    """Every piece of the film's text the run recorded: stories, summary, title, subtitle."""
    attempt = Path(film.plan["__attempt_dir__"])
    titles = json.loads((attempt / "cut-titles.private.json").read_text())
    story = film.plan["story"]
    told = {
        "summary": story["thesis"],
        "title": titles["title"] or "",
        "subtitle": titles["subtitle"] or "",
    }
    for episode in story["episodes"]:
        told[f"{episode['episode']} name"] = episode["title"]
        told[f"{episode['episode']} purpose"] = episode["purpose"]
    return told


@pytest.fixture
def home(tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap) -> UserHome:
    home = home_on(tmp_path / "home", fake_immich, outbound_trap.env())
    config = yaml.safe_load(home.config_path.read_text())
    config["title_screens"] = {"locale": "fr"}
    home.write_config(config)
    document = tmp_path / "household.yaml"
    document.write_text(yaml.safe_dump(household_people(lambda name: f"person-{name.lower()}")))
    imported = home.run("people", "import", "--from", str(document))
    assert imported.returncode == 0, imported.explain()
    return home


@pytest.mark.feature("titles.locale")
@pytest.mark.parametrize(
    ("film", "args"),
    [
        ("month", ("--start", "2025-07-01", "--end", "2025-07-31")),
        ("birthday", ("--person", "Kit", "--year", "2025", "--birthday", "07-05")),
    ],
)
def test_a_french_film_names_its_stories_and_tells_its_summary_in_french(
    home: UserHome, film: str, args: tuple[str, ...]
):
    told = _told(generate(home, *args, *_RENDER))

    left = {part: sorted(found) for part, text in told.items() if (found := _left_in_english(text))}
    assert not left, (left, told)
    names = " | ".join(text for part, text in told.items() if part.endswith(" name"))
    assert "Anniversaire de Kit" in names, told
    assert told["summary"].startswith("Anniversaire de Kit"), told
    if film == "birthday":
        assert told["title"] == "Anniversaire de Kit · 2025", told
    else:
        assert "Visite de Lou et Pat" in names, told
        assert "juillet" in names, told
