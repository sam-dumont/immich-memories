"""Each memory type on the fixture library: what its cut holds, in what order, over which dates.

The cuts are kept with `--no-render` and read back through `runs story`. Everything that scopes a
memory (its dates, its people, its trip, its accounts) runs before the scripted editor sees the
pool, so a picture the scope should keep out never reaches the cut.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tests.e2e.fake_library import (
    ALL_PICTURES,
    BIRTH_DATES,
    CARRIERS,
    PARTNER_PICTURES,
    TRIP_DAYS,
)
from tests.features.cli_harness import UserHome, basic_config
from tests.integration.features.cuts import cut
from tests.integration.features.immich_server import LibraryServer

# Kit's birthday at home: a cake in the morning, a party in the afternoon.
BIRTHDAY = "2025-07-05"
_PICTURES = ("--include-photos", "--no-music", "--quiet")


def _ids(pictures) -> set[str]:
    return {p.asset_id for p in pictures}


def _holding(condition: Callable[[set[str]], bool]) -> tuple[set[str], int, int]:
    """The carriers a people condition keeps, and how many videos and photos it lets in."""
    matching = [p for p in ALL_PICTURES if condition(set(p.people))]
    return (
        _ids(p for p in matching if p.shipped),
        sum(p.is_video for p in matching),
        sum(not p.is_video for p in matching),
    )


def _candidates(output: str) -> tuple[int, int]:
    found = re.search(r"Candidates: (\d+) video, (\d+) photo", output)
    assert found, output
    return int(found.group(1)), int(found.group(2))


# ── year, season ─────────────────────────────────────────────────────────────


@pytest.mark.feature("memory-type.year-in-review")
def test_a_year_in_review_plays_the_year_in_capture_order_and_goes_short_on_a_thin_year(
    library_home: UserHome,
):
    year = cut(
        library_home, "generate", "--memory-type", "year_in_review", "--year", "2025", *_PICTURES
    )

    pictures = year.pictures()
    assert "Memory: year_in_review" in year.output
    assert "Date range: Year 2025" in year.output
    # The whole year's stories, in the order they were taken.
    assert _ids(pictures) == _ids(CARRIERS)
    assert [p.taken_at for p in pictures] == sorted(p.taken_at for p in pictures)
    assert [s.at for s in year.shots] == sorted(s.at for s in year.shots)
    # It aims for ten minutes; one month of material lands far short, and the run says by how much.
    assert "editorial 600s" in year.output, year.result.explain()
    short = re.search(
        r"Selected ([\d.]+)s of pictures and video for a ([\d.]+)s memory", year.output
    )
    assert short and float(short.group(1)) < float(short.group(2)), year.result.explain()
    estimated = re.search(r"Estimated final duration: ([\d.]+)s", year.output)
    assert estimated and float(estimated.group(1)) < 600 / 2
    # Month dividers only appear across four months or more; one month gets none.
    assert "Month dividers: none needed (one selected month)" in year.output


def _dry(home: UserHome, *args: str) -> str:
    result = home.run("generate", *args, *_PICTURES, "--dry-run", scripted_selection=True)
    assert result.returncode == 0, result.explain()
    return result.output


@pytest.mark.feature("memory-type.season")
def test_a_season_covers_three_months_for_about_three_minutes_and_flips_in_the_south(
    library_home: UserHome,
):
    summer = _dry(library_home, "--memory-type", "season", "--season", "summer", "--year", "2025")
    southern_winter = _dry(
        library_home,
        "--memory-type",
        "season",
        "--season",
        "winter",
        "--year",
        "2025",
        "--hemisphere",
        "south",
    )
    southern_summer = _dry(
        library_home,
        "--memory-type",
        "season",
        "--season",
        "summer",
        "--year",
        "2025",
        "--hemisphere",
        "south",
    )

    assert "Date range: Jun 01, 2025 - Aug 31, 2025" in summer
    assert "Target duration: 195.0s" in summer
    # June to August is winter down south, and summer moves to December to February.
    assert "Date range: Jun 01, 2025 - Aug 31, 2025" in southern_winter
    assert re.search(r"Dec 01, 2025 - Feb 28, 2026", southern_summer), southern_summer


# ── people ───────────────────────────────────────────────────────────────────


@pytest.mark.feature("memory-type.person-spotlight")
def test_a_person_spotlight_keeps_only_pictures_the_person_is_recognised_on(
    library_home: UserHome,
):
    spotlight = cut(
        library_home,
        "generate",
        "--memory-type",
        "person_spotlight",
        "--person",
        "Charlie",
        "--year",
        "2025",
        *_PICTURES,
    )
    carriers, videos, photos = _holding(lambda people: "Charlie" in people)

    # Other shots of the same scenes, where Immich recognised nobody, never enter the pool.
    assert _candidates(spotlight.output) == (videos, photos)
    assert _ids(spotlight.pictures()) == carriers
    assert all("Charlie" in p.people for p in spotlight.pictures())


@pytest.mark.feature("memory-type.multi-person")
def test_several_people_need_each_other_on_the_same_picture_unless_matched_with_or(
    library_home: UserHome,
):
    people = ("--person", "Kit", "--person", "Charlie")
    together = cut(
        library_home,
        "generate",
        "--memory-type",
        "multi_person",
        *people,
        "--year",
        "2025",
        *_PICTURES,
    )
    either = cut(
        library_home,
        "generate",
        "--memory-type",
        "multi_person",
        *people,
        "--person-match",
        "or",
        "--year",
        "2025",
        *_PICTURES,
    )

    both = _holding(lambda p: {"Kit", "Charlie"} <= p)
    any_of = _holding(lambda p: bool({"Kit", "Charlie"} & p))
    assert _candidates(together.output) == both[1:]
    assert _ids(together.pictures()) == both[0]
    assert _candidates(either.output) == any_of[1:]
    assert _ids(either.pictures()) == any_of[0]
    # Kit alone in the fountain, Charlie alone on the bike in Copenhagen: in the OR film only.
    assert both[0] < any_of[0]


@pytest.mark.feature("people.expression")
def test_a_grouped_condition_binds_and_tighter_than_or_on_each_picture(library_home: UserHome):
    grouped = cut(
        library_home,
        "generate",
        "--memory-type",
        "multi_person",
        "--year",
        "2025",
        "--people-expression",
        '"Charlie" AND ("Kit" OR "Robin")',
        *_PICTURES,
    )
    ungrouped = library_home.run(
        "generate",
        "--memory-type",
        "multi_person",
        "--year",
        "2025",
        "--people-expression",
        '"Kit" OR "Robin" AND "Charlie"',
        *_PICTURES,
        "--dry-run",
        scripted_selection=True,
    )

    expected = _holding(lambda p: "Charlie" in p and bool({"Kit", "Robin"} & p))
    assert _candidates(grouped.output) == expected[1:]
    assert _ids(grouped.pictures()) == expected[0]
    # Without brackets AND binds first: Kit on their own counts, Robin needs Charlie.
    kit_or_robin_with_charlie = _holding(lambda p: "Kit" in p or {"Robin", "Charlie"} <= p)
    assert ungrouped.returncode == 0, ungrouped.explain()
    assert _candidates(ungrouped.output) == kit_or_robin_with_charlie[1:]
    assert kit_or_robin_with_charlie[1:] != expected[1:]


@pytest.mark.feature("people.expression")
def test_trips_refuse_a_grouped_people_condition(library_home: UserHome):
    result = library_home.run(
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2025",
        "--people-expression",
        '"Kit"',
        "--no-render",
        scripted_selection=True,
    )

    assert result.returncode != 0
    assert "not trips, albums" in result.output, result.explain()


@pytest.mark.feature("memory-type.birthday")
def test_a_birthday_runs_the_year_ending_on_it_and_looks_back_at_earlier_ones(
    library_home: UserHome,
):
    # The party at home, 5 July: the person's year runs from 6 July 2024 to the party.
    birthday = cut(
        library_home,
        "generate",
        "--person",
        "Kit",
        "--year",
        "2025",
        "--birthday",
        "07-05",
        *_PICTURES,
    )

    kept = birthday.pictures()
    assert kept and all("Kit" in p.people for p in kept)
    assert _ids(kept) == {p.asset_id for p in CARRIERS if "Kit" in p.people and p.day <= BIRTHDAY}
    # Five earlier birthdays are looked at; the library starts in 2025, so none holds anything.
    assert "history: 0 of 5 earlier windows hold material" in birthday.output
    assert "Title: Kit's birthday · 2025" in birthday.output


@pytest.mark.feature("memory-type.birthday")
def test_a_birthday_refuses_a_person_with_no_birth_date(
    library_home: UserHome, immich: LibraryServer
):
    """With no birth date in Immich, a birthday film says where to set one and stops."""
    kit = immich.person_of("person-kit")
    with httpx.Client(
        base_url=f"{immich.base_url}/api", headers={"x-api-key": immich.api_key}
    ) as api:
        api.put(f"/people/{kit}", json={"birthDate": None}).raise_for_status()
        try:
            result = library_home.run(
                "generate",
                "--person",
                "Kit",
                "--year",
                "2025",
                "--birthday",
                *_PICTURES,
                "--no-render",
                scripted_selection=True,
            )
        finally:
            api.put(f"/people/{kit}", json={"birthDate": BIRTH_DATES["Kit"]}).raise_for_status()

    assert result.returncode == 1
    assert "Kit has no birth date" in result.output, result.explain()
    assert "runs render" not in result.output


# ── trips ────────────────────────────────────────────────────────────────────

_TRIP_PLACE = "Denmark → Sweden → Finland → Norway"
_TRIP_LINE = f"Generating trip: {_TRIP_PLACE} ({TRIP_DAYS[0]} to {TRIP_DAYS[1]}"


@pytest.mark.feature("memory-type.trip")
def test_trip_lists_what_the_gps_found_and_films_the_one_picked(library_home: UserHome):
    listed = library_home.run(
        "generate", "--memory-type", "trip", "--year", "2025", *_PICTURES, scripted_selection=True
    )
    by_index = cut(
        library_home,
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2025",
        "--trip-index",
        "1",
        *_PICTURES,
    )
    near = _dry(
        library_home, "--memory-type", "trip", "--year", "2025", "--near-date", "2025-07-20"
    )
    by_month = _dry(library_home, "--memory-type", "trip", "--year", "2025", "--month", "7")

    assert listed.returncode == 0, listed.explain()
    assert re.search(
        rf"│ 1 │ {_TRIP_PLACE}\s*│ {TRIP_DAYS[0]} to {TRIP_DAYS[1]} │\s*19 │", listed.stdout
    ), listed.stdout
    assert "runs render" not in listed.output
    # The trip's dates, and only what can say it was away: every clip, and the photos whose
    # GPS puts them on the road (a photo without GPS cannot).
    expected = {
        p.asset_id
        for p in CARRIERS
        if TRIP_DAYS[0] <= p.day <= TRIP_DAYS[1] and (p.is_video or p.place is not None)
    }
    assert _ids(by_index.pictures()) == expected
    assert "Memory: trip" in by_index.output
    assert _TRIP_LINE in near
    assert _TRIP_LINE in by_month


@pytest.mark.feature("memory-type.trip")
def test_all_trips_films_every_trip_found(library_home: UserHome):
    every = library_home.run(
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2025",
        "--all-trips",
        *_PICTURES,
        "--no-render",
        scripted_selection=True,
    )

    assert every.returncode == 0, every.explain()
    assert every.output.count("Generating trip:") == 1
    assert _TRIP_LINE in every.output
    assert re.search(r"runs render \d{8}_\d{6}_[0-9a-f]{4}", every.output), every.explain()


# ── special days ─────────────────────────────────────────────────────────────


def _event(day: str, start: str, end: str, members: list[str], title: str) -> dict:
    """A catalogued event as `days-export` writes one: its exact pictures and their run."""
    digest = hashlib.sha256(json.dumps(sorted(members), separators=(",", ":")).encode())
    return {
        "event_id": f"special-event-{digest.hexdigest()[:24]}",
        "asset_ids": members,
        "day": day,
        "start": f"{day}T{start}:00+00:00",
        "end": f"{day}T{end}:00+00:00",
        "title": title,
        "subtitle": "",
        "what": "",
    }


@pytest.mark.feature("memory-type.special-day")
def test_a_special_day_films_its_events_run_and_needs_event_id_when_the_day_has_two(
    library_home: UserHome, immich: LibraryServer, tmp_path: Path
):
    birthday = [p for p in CARRIERS if p.day == BIRTHDAY]
    morning, party = birthday[:2], birthday[2:]
    catalogue = [
        _event(BIRTHDAY, "05:00", "06:30", immich.ids_of(p.asset_id for p in morning), "The cake"),
        _event(BIRTHDAY, "14:00", "17:30", immich.ids_of(p.asset_id for p in party), "The party"),
    ]
    (tmp_path / "days.json").write_text(json.dumps(catalogue))
    day = ("generate", "--memory-type", "special_day", "--day", BIRTHDAY, *_PICTURES)

    imported = library_home.run("days-import", "--from", str(tmp_path / "days.json"))
    try:
        ambiguous = library_home.run(*day, "--no-render", scripted_selection=True)
        chosen = cut(library_home, *day, "--event-id", catalogue[1]["event_id"])
    finally:
        (tmp_path / "empty.json").write_text("[]")
        library_home.run("days-import", "--from", str(tmp_path / "empty.json"))

    assert imported.returncode == 0, imported.explain()
    assert ambiguous.returncode != 0
    assert "--event-id" in ambiguous.output, ambiguous.explain()
    assert _ids(chosen.pictures()) == _ids(party)
    assert "Title: The party" in chosen.output


@pytest.mark.feature("memory-type.special-day")
def test_a_day_the_catalogue_never_found_is_scoped_to_itself(library_home: UserHome):
    day = cut(
        library_home,
        "generate",
        "--memory-type",
        "special_day",
        "--day",
        BIRTHDAY,
        *_PICTURES,
    )

    assert "Date range: Jul 05, 2025 - Jul 05, 2025" in day.output
    assert _ids(day.pictures()) == {p.asset_id for p in CARRIERS if p.day == BIRTHDAY}


# ── accounts ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def household_home(tmp_path_factory: pytest.TempPathFactory, immich: LibraryServer):
    """A Basic install with a second Immich account, `partner`, on the same server."""
    home = UserHome(tmp_path_factory.mktemp("household-home"))
    config = basic_config(immich.base_url, immich.api_key, home)
    config["immich"]["accounts"] = {
        "partner": {
            "url": immich.base_url,
            "api_key": immich.partner_api_key,
            "api_version": "auto",
        }
    }
    home.write_config(config)
    return home


_FOREST_DAY = ("generate", "--start", "2025-07-06", "--end", "2025-07-06", *_PICTURES)
_BOTH = (*ALL_PICTURES, *PARTNER_PICTURES)


@pytest.mark.feature("accounts.read-both")
def test_naming_both_accounts_puts_the_partners_pictures_in_the_film(household_home: UserHome):
    both = cut(household_home, *_FOREST_DAY, "--accounts", "primary,partner")
    primary = cut(household_home, *_FOREST_DAY)

    partner = _ids(PARTNER_PICTURES)
    forest = {p.asset_id for p in CARRIERS if p.day == "2025-07-06"}
    assert _ids(both.pictures(_BOTH)) == forest | partner
    assert _ids(primary.pictures(_BOTH)) == forest
    # One film, in capture order across both phones.
    taken = [p.taken_at for p in both.pictures(_BOTH)]
    assert taken == sorted(taken)


@pytest.mark.feature("accounts.read-both")
def test_an_unknown_account_fails_before_any_request(tmp_path: Path):
    # Nothing listens on this Immich: a run that asked it anything would fail on the connection.
    home = UserHome(tmp_path / "home")
    config = basic_config("http://127.0.0.1:9", "unused-key", home)
    config["immich"]["accounts"] = {"partner": {"url": "http://127.0.0.1:9", "api_key": "k"}}
    home.write_config(config)

    result = home.run(*_FOREST_DAY, "--accounts", "primary,nobody", "--no-render")

    assert result.returncode == 2
    assert "Immich account 'nobody' is not configured (configured: primary, partner)" in (
        result.output
    ), result.explain()
    assert "cannot reach" not in result.output


@pytest.mark.feature("accounts.read-both")
def test_albums_and_trips_refuse_a_second_account(household_home: UserHome):
    album = household_home.run(
        "generate",
        "--from-album",
        "The road north",
        "--accounts",
        "primary,partner",
        "--no-render",
        scripted_selection=True,
    )
    trip = household_home.run(
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2025",
        "--accounts",
        "primary,partner",
        "--no-render",
        scripted_selection=True,
    )

    for refused in (album, trip):
        assert refused.returncode == 2, refused.explain()
        assert "--accounts reads date-range memories, not albums or trips" in refused.output


# ── what the owner asks of the cut ───────────────────────────────────────────


@pytest.mark.feature("cut.include-exclude")
def test_include_and_exclude_reach_the_cut(library_home: UserHome, immich: LibraryServer):
    """The scripted editor honours what the run hands it; tests/features/test_editor_pool.py
    holds the real editor to the same two lists."""
    birthday = cut(
        library_home,
        "generate",
        "--start",
        BIRTHDAY,
        "--end",
        BIRTHDAY,
        *_PICTURES,
        "--include",
        immich.id_of("birthday-cupcakes-2"),
        "--exclude",
        immich.id_of("birthday-cake"),
    )

    kept = _ids(birthday.pictures())
    assert "birthday-cupcakes-2" in kept
    assert "birthday-cake" not in kept
    assert kept == {p.asset_id for p in CARRIERS if p.day == BIRTHDAY} - {"birthday-cake"} | {
        "birthday-cupcakes-2"
    }
    why = library_home.run("runs", "why", immich.id_of("birthday-cake"), "--run", birthday.run_id)
    assert "left out" in why.stdout, why.explain()


@pytest.mark.feature("photos.video-only")
def test_no_photos_or_photos_disabled_make_a_video_only_film(library_home: UserHome):
    month = ("generate", "--start", "2025-07-01", "--end", "2025-07-31", "--no-music", "--quiet")
    flag = cut(library_home, *month, "--no-photos")
    config = cut(library_home, *month, env={"IMMICH_MEMORIES_PHOTOS__ENABLED": "false"})

    videos = {p.asset_id for p in CARRIERS if p.is_video}
    for film in (flag, config):
        assert _candidates(film.output)[1] == 0, film.output
        assert _ids(film.pictures()) == videos


@pytest.mark.feature("generate.connects-before-hardware")
def test_an_unreachable_immich_stops_generate_before_hardware_and_is_recorded(
    tmp_path: Path, library_home: UserHome, departure_film
):
    home = UserHome(tmp_path / "home")
    # Nothing listens here.
    home.write_config(basic_config("http://127.0.0.1:9", "unused-key", home))

    failed = home.run(*_FOREST_DAY, "--no-render", scripted_selection=True)
    history = home.run("runs", "list", "--status", "failed")

    assert failed.returncode == 1
    assert "cannot reach 127.0.0.1:9" in failed.output, failed.explain()
    # Title kernels and the system probe come after Immich answers; neither ran.
    assert "Title kernels" not in failed.output
    run_ids = re.findall(r"\d{8}_\d{6}_[0-9a-f]{4}", history.stdout)
    assert len(run_ids) == 1, history.explain()
    shown = home.run("runs", "show", run_ids[0])
    assert "failed" in shown.stdout
    assert "System Info" not in shown.stdout
    # A run that reached Immich records the machine it ran on.
    assert "System Info" in library_home.run("runs", "show", departure_film.run_id).stdout
