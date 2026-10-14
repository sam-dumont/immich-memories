"""The people registry from the terminal: its owner, its file, its bindings, its saved groups.

Every test drives the real CLI in a sealed home against the session's Immich and reads what
the registry says afterwards (`people show`, `people owner`, `people group list`) and what a
film cut with it holds. Cuts keep the scripted editor (`--no-render`); the people they may
choose from is the production resolution of names, ids, bindings and groups.
"""

from __future__ import annotations

import re
import stat
from datetime import date
from pathlib import Path

import pytest
import yaml

from tests.e2e.fake_library import ALL_PICTURES, PARTNER_PICTURES, household_people
from tests.features.cli_harness import UserHome, basic_config
from tests.integration.features.cuts import cut
from tests.integration.features.immich_server import LibraryServer

_PICTURES = ("--include-photos", "--no-music", "--quiet")
# The day Kit's friends came round: Kit, Jo, Alex and Mo are all on it.
_FRIENDS_DAY = "2025-07-08"
_FOREST_DAY = "2025-07-06"


def _household(home: UserHome, immich: LibraryServer) -> UserHome:
    """Give a home the household's registry, as its owner set it up."""
    document = home.root / "household.yaml"
    document.write_text(yaml.safe_dump(household_people(lambda n: immich.person_of(_id(n)))))
    imported = home.run("people", "import", "--from", str(document))
    assert imported.returncode == 0, imported.explain()
    return home


def _id(name: str) -> str:
    return f"person-{name.lower()}"


def _ok(home: UserHome, *args: str) -> str:
    result = home.run(*args)
    assert result.returncode == 0, result.explain()
    return result.output


def _candidates(output: str) -> int:
    """How many pictures the cut could choose from (videos and photos)."""
    found = re.search(r"Candidates: (\d+) video, (\d+) photo", output)
    assert found, output
    return int(found.group(1)) + int(found.group(2))


def _on(day: str, *names: str) -> int:
    """The pictures of that day showing any of these people."""
    return sum(1 for p in ALL_PICTURES if p.day == day and set(p.people) & set(names))


def _registry(home: UserHome) -> dict[str, str]:
    """`people show`: each person's name by id."""
    shown = _ok(home, "people", "show")
    return {
        m["id"]: m["name"] for m in re.finditer(r"^  (?P<name>\S.*?)\s{2,}(?P<id>\S+)", shown, re.M)
    }


# ── whose library it is ──────────────────────────────────────────────────────


@pytest.mark.feature("people.owner")
def test_the_owner_you_name_outlasts_every_scan_and_nobody_is_an_answer(
    fresh_home: UserHome, immich: LibraryServer
):
    guessed = _ok(fresh_home, "people", "scan", "--owner", "Charlie")
    named = _ok(fresh_home, "people", "owner", "Kit")
    _ok(fresh_home, "people", "scan", "--owner", "Charlie")
    after_scan = _ok(fresh_home, "people", "owner")
    nobody = _ok(fresh_home, "people", "owner", "--nobody")
    _ok(fresh_home, "people", "scan", "--owner", "Charlie")
    still_nobody = _ok(fresh_home, "people", "owner")
    partner = _ok(fresh_home, "people", "owner", "--account", "partner", "Robin")
    partner_answer = _ok(fresh_home, "people", "owner", "--account", "partner")

    # --owner on a scan is a guess, for a library nobody has answered for.
    assert "owner: Charlie" in guessed
    assert f"Kit ({immich.person_of(_id('Kit'))}) owns the primary account's library" in named
    # Said once, no scan changes it, whatever --owner it is given.
    assert "owner: Kit (you confirmed it)" in after_scan
    assert "Nobody owns the primary account's library" in nobody
    assert "primary: nobody in this library (you confirmed it)" in still_nobody
    assert "owns the partner account's library" in partner
    assert "partner: Robin (you confirmed it)" in partner_answer


# ── the registry as a file ───────────────────────────────────────────────────


@pytest.mark.feature("people.export-import")
def test_an_edited_export_comes_back_whole_and_a_broken_one_changes_nothing(
    fresh_home: UserHome, immich: LibraryServer, tmp_path: Path
):
    home = _household(fresh_home, immich)
    exported = tmp_path / "people.yaml"
    _ok(home, "people", "export", "--to", str(exported))
    document = yaml.safe_load(exported.read_text())
    nico = immich.person_of(_id("Nico"))
    renamed = {**document, "people": [_renamed(p, nico, "Nicolas") for p in document["people"]]}
    edited = tmp_path / "edited.yaml"
    edited.write_text(yaml.safe_dump(renamed))
    broken = dict(renamed)
    broken["people"] = [dict(p) for p in renamed["people"]]
    broken["people"][0]["birth_date"] = "1987-14-03"
    broken["people"][1]["ids"] = []
    broken_file = tmp_path / "broken.yaml"
    broken_file.write_text(yaml.safe_dump(broken))

    without_replace = home.run("people", "import", "--from", str(edited))
    refused = home.run("people", "import", "--from", str(broken_file), "--replace")
    before = _registry(home)
    replaced = home.run("people", "import", "--from", str(edited), "--replace")
    after = _registry(home)

    # The export is the registry, readable by its owner alone (names and birth dates).
    assert stat.S_IMODE(exported.stat().st_mode) == 0o600
    assert {p["name"] for p in document["people"]} >= {"Robin", "Kit", "Nico"}
    # A registry is only replaced on purpose, and only by a file that is valid throughout.
    assert without_replace.returncode == 1
    assert "pass --replace to overwrite them" in without_replace.output
    assert refused.returncode == 1
    assert "nothing changed" in refused.output
    assert "people[0]: `birth_date` must be a date" in refused.output, refused.explain()
    assert "people[1]: `ids` must be a non-empty list" in refused.output, refused.explain()
    assert before[nico] == "Nico"
    assert replaced.returncode == 0, replaced.explain()
    assert after[nico] == "Nicolas"
    assert {k: v for k, v in after.items() if k != nico} == {
        k: v for k, v in before.items() if k != nico
    }


def _renamed(person: dict, person_id: str, name: str) -> dict:
    return {**person, "name": name} if person_id in person["ids"] else person


# ── another account's face ───────────────────────────────────────────────────


@pytest.fixture
def two_accounts(fresh_home: UserHome, immich: LibraryServer) -> UserHome:
    """The household's home, reading a second account, `partner`, on the same Immich."""
    config = basic_config(immich.base_url, immich.api_key, fresh_home)
    config["immich"]["accounts"] = {
        "partner": {"url": immich.base_url, "api_key": immich.partner_api_key}
    }
    fresh_home.write_config(config)
    return _household(fresh_home, immich)


@pytest.mark.feature("people.bind")
def test_a_bound_face_brings_the_other_accounts_pictures_into_the_persons_film(
    two_accounts: UserHome, immich: LibraryServer
):
    spotlight = (
        "generate",
        "--memory-type",
        "person_spotlight",
        "--person",
        "Pat",
        "--start",
        _FOREST_DAY,
        "--end",
        _FOREST_DAY,
        "--accounts",
        "primary,partner",
        *_PICTURES,
    )
    # The partner's Immich knows Pat under its own id and another name.
    face = immich.person_of("partner-person-02")
    unbound = cut(two_accounts, *spotlight)
    bound = _ok(two_accounts, "people", "bind", "Pat", "--account", "partner", "--id", face)
    again = _ok(two_accounts, "people", "bind", "Pat", "--account", "partner", "--id", face)
    with_binding = cut(two_accounts, *spotlight)
    registry = _registry(two_accounts)

    partner_shot = {p.asset_id for p in PARTNER_PICTURES}
    library = (*ALL_PICTURES, *PARTNER_PICTURES)
    assert not partner_shot & {p.asset_id for p in unbound.pictures(library)}
    assert f"Bound {face} (partner account) to Pat" in bound
    # Binding the same id again changes nothing.
    assert f"{face} is already bound to Pat" in again and "nothing changed" in again
    assert partner_shot <= {p.asset_id for p in with_binding.pictures(library)}
    assert _candidates(with_binding.output) == _candidates(unbound.output) + len(partner_shot)
    # The binding only adds an id: Pat keeps the name, and no partner person appears.
    assert registry[immich.person_of(_id("Pat"))] == "Pat"
    assert face not in registry


# ── saved groups ─────────────────────────────────────────────────────────────


@pytest.mark.feature("people.saved-groups")
def test_a_saved_group_picks_its_people_by_id_and_removing_it_keeps_them(
    fresh_home: UserHome, immich: LibraryServer
):
    home = _household(fresh_home, immich)
    kit, jo = immich.person_of(_id("Kit")), immich.person_of(_id("Jo"))
    friends = ("--start", _FRIENDS_DAY, "--end", _FRIENDS_DAY, *_PICTURES)

    saved = _ok(home, "people", "group", "add", "kids", f'"{kit}" OR "{jo}"')
    listed = _ok(home, "people", "group", "list")
    film = cut(home, "generate", "--memory-type", "multi_person", "--group", "kids", *friends)
    removed = _ok(home, "people", "group", "rm", "kids")
    listed_after = _ok(home, "people", "group", "list")
    gone = home.run(
        "generate", "--memory-type", "multi_person", "--group", "kids", *friends, "--no-render"
    )

    assert "Saved group 'kids'" in saved
    assert "kids" in listed and kit in listed
    # The group stands for its people, by their ids: everyone either of them is on that day.
    assert _candidates(film.output) == _on(_FRIENDS_DAY, "Kit", "Jo")
    assert all({"Kit", "Jo"} & set(p.people) for p in film.pictures())
    title = re.search(r"^Title: (.+)$", film.output, re.M)
    assert title, film.output
    # The title names the people, never their ids.
    assert "Kit" in title.group(1) and "Jo" in title.group(1)
    assert "person-" not in title.group(1) and kit not in title.group(1)
    assert "Removed group 'kids'" in removed
    assert "No saved groups yet" in listed_after
    assert gone.returncode != 0
    assert "kids" in gone.output
    registry = _registry(home)
    assert registry[kit] == "Kit" and registry[jo] == "Jo"


# ── two people, one name ─────────────────────────────────────────────────────


@pytest.mark.feature("people.duplicate-name-warning")
def test_a_shared_name_picks_both_people_and_an_id_picks_one(
    fresh_home: UserHome, immich: LibraryServer, tmp_path: Path
):
    home = _household(fresh_home, immich)
    kit, jo = immich.person_of(_id("Kit")), immich.person_of(_id("Jo"))
    exported = tmp_path / "people.yaml"
    _ok(home, "people", "export", "--to", str(exported))
    document = yaml.safe_load(exported.read_text())
    # Jo is renamed Kit in the registry: two people, one name.
    document["people"] = [_renamed(p, jo, "Kit") for p in document["people"]]
    exported.write_text(yaml.safe_dump(document))
    _ok(home, "people", "import", "--from", str(exported), "--replace")
    day = ("--start", _FRIENDS_DAY, "--end", _FRIENDS_DAY, *_PICTURES)

    by_name = cut(home, "generate", "--person", "Kit", *day)
    by_id = cut(home, "generate", "--person", kit, *day)

    assert "'Kit' is 2 people in the people store; the film looks for all:" in by_name.output
    assert f"Kit (id {kit};" in by_name.output
    assert f"Kit (id {jo};" in by_name.output
    assert "Use --person <id> to choose one." in by_name.output
    assert _candidates(by_name.output) == _on(_FRIENDS_DAY, "Kit", "Jo")
    # An id is one person, whoever else carries the name.
    assert "people in the people store" not in by_id.output
    assert _candidates(by_id.output) == _on(_FRIENDS_DAY, "Kit")
    assert _candidates(by_id.output) < _candidates(by_name.output)


# ── a people memory with no dates ────────────────────────────────────────────


def _window(home: UserHome, *args: str) -> str:
    result = home.run("generate", *args, *_PICTURES, "--dry-run", scripted_selection=True)
    assert result.returncode == 0, result.explain()
    found = re.search(r"Date range: (.+)$", result.output, re.M)
    assert found, result.explain()
    return found.group(1).strip()


def _shown(day: date) -> str:
    return f"{day:%b %d, %Y}"


@pytest.mark.feature("people.no-dates-window")
def test_a_people_memory_without_dates_runs_from_the_first_possible_day_to_today(
    library_home: UserHome,
):
    today = date.today()
    spotlight = _window(library_home, "--memory-type", "person_spotlight", "--person", "Kit")
    either = _window(
        library_home, "--memory-type", "multi_person", "--people-expression", '"Kit" OR "Pat"'
    )
    both = _window(
        library_home,
        "--memory-type",
        "multi_person",
        "--people-expression",
        '("Pat" OR "Robin") AND "Kit"',
    )
    given = _window(
        library_home,
        "--memory-type",
        "person_spotlight",
        "--person",
        "Kit",
        "--start",
        "2019-06-01",
        "--end",
        "2025-12-31",
    )

    ends = {f" - {_shown(today)}", f" - {_shown(date.fromordinal(today.toordinal() - 1))}"}
    # Kit was born on 2020-07-05: no picture of Kit can be older.
    assert spotlight.startswith("Jul 05, 2020") and spotlight[12:] in ends, spotlight
    # An OR opens with the oldest it accepts (Pat, 1955); an AND waits for the youngest.
    assert either.startswith("Apr 20, 1955"), either
    assert both.startswith("Jul 05, 2020"), both
    # Dates you give are never moved.
    assert given == "Jun 01, 2019 - Dec 31, 2025"


# ── runs about one person ────────────────────────────────────────────────────


@pytest.mark.feature("runs.list-by-person")
def test_runs_list_person_lists_only_that_persons_runs(fresh_home: UserHome):
    def spotlight(name: str) -> str:
        return cut(
            fresh_home,
            "generate",
            "--memory-type",
            "person_spotlight",
            "--person",
            name,
            "--start",
            _FOREST_DAY,
            "--end",
            "2025-07-07",
            *_PICTURES,
        ).run_id

    kit, pat = spotlight("Kit"), spotlight("Pat")
    everyone = cut(fresh_home, "generate", "--start", _FOREST_DAY, "--end", _FOREST_DAY, *_PICTURES)

    listed = _ok(fresh_home, "runs", "list", "--person", "Kit")
    nobody = _ok(fresh_home, "runs", "list", "--person", "Lou")
    every_run = _ok(fresh_home, "runs", "list")

    assert kit in listed
    assert pat not in listed and everyone.run_id not in listed
    assert "Showing 1 run" in listed, listed
    assert "No runs found" in nobody
    assert {kit, pat, everyone.run_id} <= set(re.findall(r"\d{8}_\d{6}_[0-9a-f]{4}", every_run))
