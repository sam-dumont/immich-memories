"""Reading the library, scoping a film, the store, and what never leaves the machine."""

from __future__ import annotations

import json
import re

import pytest

from tests.e2e.fake_immich import ALBUMS
from tests.features.cli_harness import OutboundTrap, UserHome, film_facts
from tests.integration.features.library import (
    GARDEN_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    render,
)

_RUN_ID = re.compile(r"\d{8}_\d{6}_[0-9a-f]{4}")


def _cut(home: UserHome, *args: str) -> tuple[str, str]:
    """`generate ... --no-render`: the run id it kept and everything it printed."""
    result = home.run(*args, "--no-render", scripted_selection=True)
    assert result.returncode == 0, result.explain()
    found = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", result.output)
    assert found, result.explain()
    return found[0], result.output


@pytest.mark.feature("library.years")
def test_years_lists_the_years_the_library_holds(library_home: UserHome):
    result = library_home.run("years")

    assert result.returncode == 0, result.explain()
    assert re.findall(r"\b(20\d\d)\b", result.stdout) == ["2024"]


@pytest.mark.feature("automation.suggest")
def test_auto_suggest_ranks_candidates_with_reasons_in_a_stable_order(fresh_home: UserHome):
    # A home with no history: what other tests filmed would leave less to propose.
    first = fresh_home.run("auto", "suggest", "--json")
    second = fresh_home.run("auto", "suggest", "--json")

    assert first.returncode == 0, first.explain()
    candidates = json.loads(first.stdout)
    assert 0 < len(candidates) <= 10
    assert all(c["reason"] and c["memory_key"] for c in candidates)
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert json.loads(second.stdout) == candidates


@pytest.mark.feature("generate.period")
def test_period_scopes_the_film_from_the_start_date(library_home: UserHome):
    result = library_home.run(
        "generate", "--start", GARDEN_DAY, "--period", "1w", "--dry-run", scripted_selection=True
    )

    assert result.returncode == 0, result.explain()
    assert "Date range: Jun 08, 2024 - Jun 14, 2024" in result.output, result.explain()


@pytest.mark.feature("memory-type.album")
def test_an_album_film_reads_its_pictures_from_the_album_and_takes_its_name(
    library_home: UserHome,
):
    album = ALBUMS[0]
    first_day, last_day = album["startDate"][:10], album["endDate"][:10]

    cut_id, output = _cut(
        library_home,
        "generate",
        "--from-album",
        album["albumName"],
        "--include-photos",
        "--no-music",
        "--quiet",
    )
    story = library_home.run("runs", "story", cut_id)

    assert "Memory: album" in output
    assert f"Title: {album['albumName']}" in output
    days = re.findall(r"^\s+\d+:\d\d\s+(\d{4}-\d\d-\d\d)\s", story.stdout, re.M)
    assert days, story.explain()
    assert all(first_day <= day <= last_day for day in days), days


@pytest.mark.feature("titles.override")
def test_title_replaces_the_title_the_run_would_choose(library_home: UserHome, tmp_path):
    cut_id, plan = _cut(library_home, *day_args(QUIET_DAY), "--title", "A Feature Title")
    run = render(
        library_home,
        *day_args(QUIET_DAY),
        "--title",
        "A Feature Title",
        "--output",
        str(tmp_path / "titled.mp4"),
        into=tmp_path,
    )
    shown = library_home.run("runs", "show", run.run_id)

    assert "Title: A Feature Title" in plan
    assert re.search(r"Title From\s*│\s*override", shown.stdout), shown.explain()


@pytest.mark.feature("output.format")
def test_format_h265_encodes_the_film_in_hevc(library_home: UserHome, tmp_path):
    run = render(
        library_home,
        *day_args(QUIET_DAY),
        "--format",
        "h265",
        "--output",
        str(tmp_path / "hevc.mp4"),
        into=tmp_path,
    )

    assert film_facts(run.film).codec == "hevc"


@pytest.mark.feature("cli.quiet-progress")
def test_quiet_prints_plain_lines_and_no_live_display(garden_film: RenderedRun):
    result = garden_film.result

    assert "\r" not in result.output
    assert "\x1b[" not in result.output
    assert re.search(r"\[INFO\] immich_memories", result.stderr)


@pytest.mark.feature("runs.stats")
def test_runs_stats_summarises_the_history(library_home: UserHome, garden_film):
    result = library_home.run("runs", "stats")

    assert result.returncode == 0, result.explain()
    total = re.search(r"Total Runs\s*│\s*(\d+)", result.stdout)
    completed = re.search(r"Completed Runs\s*│\s*(\d+)", result.stdout)
    assert total and completed, result.explain()
    assert int(total.group(1)) >= int(completed.group(1)) >= 1


@pytest.mark.feature("privacy.immich-only-by-default")
@pytest.mark.feature("privacy.outside-calls-opt-in")
def test_a_basic_film_talks_to_nothing_but_the_configured_immich(
    library_home: UserHome, garden_film, outbound_trap: OutboundTrap
):
    # The session's film, plus the commands a first run tries, all went through the trap.
    for command in (("preflight",), ("capabilities", "--json"), ("report", garden_film.run_id)):
        # The scripted route stands in for `models fetch`, which a Basic install has run.
        result = library_home.run(*command, scripted_selection=True)
        assert result.returncode == 0, result.explain()

    assert outbound_trap.requests == []


@pytest.mark.feature("store.status")
def test_store_status_names_the_backend_revision_and_row_counts(library_home, garden_film):
    result = library_home.run("store", "status")

    assert result.returncode == 0, result.explain()
    assert re.search(r"Backend:\s+sqlite", result.stdout)
    assert "(at head)" in result.stdout
    runs = re.search(r"pipeline_runs\s+(\d+)", result.stdout)
    assert runs and int(runs.group(1)) >= 1, result.explain()


@pytest.mark.feature("store.backup-restore")
def test_a_restored_backup_brings_back_what_was_deleted_after_it(library_home: UserHome, tmp_path):
    cut_id, _ = _cut(library_home, *day_args(QUIET_DAY))
    backup = tmp_path / "store-backup.db"

    backed_up = library_home.run("store", "backup", "--to", str(backup))
    library_home.run("runs", "delete", cut_id, "--yes")
    gone = library_home.run("runs", "list", "--limit", "200").stdout
    restored = library_home.run("store", "restore", "--from", str(backup), "--force")
    back = library_home.run("runs", "list", "--limit", "200").stdout

    assert backed_up.returncode == 0, backed_up.explain()
    assert backup.with_name(backup.name + ".manifest.json").is_file()
    assert cut_id not in gone
    assert restored.returncode == 0, restored.explain()
    assert cut_id in back
