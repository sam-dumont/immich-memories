"""What a finished run leaves to read, render again, report and delete."""

from __future__ import annotations

import json
import os
import re
import zipfile

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.features.cli_harness import UserHome, film_facts, films_under
from tests.integration.features.library import (
    GARDEN_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    left_out_on,
    render,
    shipped_on,
)

_STORY_LINE = re.compile(r"^\s+(\d+:\d\d)\s+(\d{4}-\d\d-\d\d)\s+(photo|video)\s", re.M)


@pytest.mark.feature("runs.list-and-show")
def test_runs_list_and_show_find_the_finished_film(library_home: UserHome, garden_film):
    listed = library_home.run("runs", "list", "--limit", "50")
    failed = library_home.run("runs", "list", "--status", "failed")
    # A partial id works while it is unambiguous.
    shown = library_home.run("runs", "show", garden_film.run_id[:-1])

    assert listed.returncode == 0, listed.explain()
    assert garden_film.run_id in listed.stdout
    assert "completed" in listed.stdout
    assert garden_film.run_id not in failed.stdout
    assert shown.returncode == 0, shown.explain()
    assert garden_film.run_id in shown.stdout
    assert garden_film.film.name in shown.stdout.replace("\n", "")


@pytest.mark.feature("runs.story")
def test_runs_story_reads_the_shots_in_playback_order(library_home: UserHome, garden_film):
    result = library_home.run("runs", "story", garden_film.run_id)

    assert result.returncode == 0, result.explain()
    shots = _STORY_LINE.findall(result.stdout)
    shipped = shipped_on(GARDEN_DAY)
    assert [kind for _, _, kind in shots] == ["video" if p.is_video else "photo" for p in shipped]
    assert {day for _, day, _ in shots} == {GARDEN_DAY}
    timecodes = [int(m) * 60 + int(s) for m, s in (t.split(":") for t, _, _ in shots)]
    assert timecodes == sorted(timecodes) and len(set(timecodes)) == len(timecodes)


@pytest.mark.feature("runs.why")
def test_runs_why_says_where_a_picture_was_kept_or_left_out(library_home: UserHome, garden_film):
    kept = shipped_on(GARDEN_DAY)[0].asset_id
    dropped = left_out_on(GARDEN_DAY)[0]

    kept_answer = library_home.run("runs", "why", kept, "--run", garden_film.run_id)
    dropped_answer = library_home.run("runs", "why", dropped, "--run", garden_film.run_id)

    assert kept_answer.returncode == 0, kept_answer.explain()
    assert "in the cut at" in kept_answer.stdout
    assert dropped_answer.returncode == 0, dropped_answer.explain()
    assert "left out" in dropped_answer.stdout
    assert "in the cut at" not in dropped_answer.stdout


@pytest.mark.feature("runs.storage")
def test_runs_storage_json_reports_the_output_directories(library_home: UserHome, garden_film):
    result = library_home.run("runs", "storage", "--json")

    assert result.returncode == 0, result.explain()
    report = json.loads(result.stdout)
    paths = [entry["path"] for entry in report["directories"]]
    assert str(garden_film.film.parent) in paths, paths


# ── a cut kept without rendering, then rendered ──────────────────────────────


@pytest.fixture(scope="module")
def saved_cut(library_home: UserHome) -> tuple[str, list]:
    """`generate --no-render`: the run id it kept and the films on disk afterwards."""
    before = films_under(library_home.videos)
    result = library_home.run(*day_args(GARDEN_DAY), "--no-render", scripted_selection=True)
    assert result.returncode == 0, result.explain()
    assert "no video was created" in result.output, result.explain()
    run_ids = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", result.output)
    assert run_ids, result.explain()
    return run_ids[0], [film for film in films_under(library_home.videos) if film not in before]


@pytest.mark.feature("generate.no-render")
def test_no_render_saves_a_real_cut_and_writes_no_film(library_home: UserHome, saved_cut):
    run_id, new_films = saved_cut

    story = library_home.run("runs", "story", run_id)

    assert new_films == []
    assert story.returncode == 0, story.explain()
    assert len(_STORY_LINE.findall(story.stdout)) == len(shipped_on(GARDEN_DAY))


@pytest.mark.feature("runs.render-saved-cut")
def test_runs_render_makes_the_film_of_a_saved_cut_as_a_new_run(library_home: UserHome, saved_cut):
    cut_id, _ = saved_cut
    before = set(films_under(library_home.videos))

    result = library_home.run("runs", "render", cut_id, "--no-music")

    assert result.returncode == 0, result.explain()
    added = [film for film in films_under(library_home.videos) if film not in before]
    assert len(added) == 1, result.explain()
    assert cut_id not in added[0].parent.name
    assert film_facts(added[0]).duration > 10


@pytest.mark.feature("generate.dry-run")
def test_dry_run_previews_the_inputs_without_a_cut_or_a_film(library_home: UserHome):
    before_runs = library_home.run("runs", "list", "--limit", "100").stdout
    before_films = films_under(library_home.videos)

    result = library_home.run(*day_args(GARDEN_DAY), "--dry-run", scripted_selection=True)

    assert result.returncode == 0, result.explain()
    assert "selection was not run" in result.output
    assert re.search(r"Candidates: \d+ video, \d+ photo", result.output), result.explain()
    assert films_under(library_home.videos) == before_films
    after_runs = library_home.run("runs", "list", "--limit", "100").stdout
    assert set(re.findall(r"\d{8}_\d{6}_[0-9a-f]{4}", after_runs)) == set(
        re.findall(r"\d{8}_\d{6}_[0-9a-f]{4}", before_runs)
    )


# ── the report ───────────────────────────────────────────────────────────────


@pytest.mark.feature("report.sections")
def test_report_shows_the_phase_table_warnings_and_redacted_logs(library_home, garden_film):
    result = library_home.run("report", garden_film.run_id)

    assert result.returncode == 0, result.explain()
    assert "| Phase | Seconds |" in result.stdout
    assert "Peak MB" in result.stdout
    assert "| render |" in result.stdout
    assert "<summary>Warnings</summary>" in result.stdout
    assert "<summary>Run logs (redacted)</summary>" in result.stdout


@pytest.mark.feature("report.json")
def test_report_json_gives_the_report_as_data(library_home: UserHome, garden_film):
    result = library_home.run("report", garden_film.run_id, "--json")

    assert result.returncode == 0, result.explain()
    report = json.loads(result.stdout)
    assert report["tier"] == "basic"
    assert report["log_counts"]["INFO"] > 0
    assert isinstance(report["missing_capabilities"], list)


@pytest.mark.feature("report.bundle")
def test_report_bundle_zips_the_report_and_the_redacted_logs(
    library_home: UserHome, garden_film, tmp_path
):
    bundle = tmp_path / "report.zip"

    result = library_home.run("report", garden_film.run_id, "--bundle", str(bundle))

    assert result.returncode == 0, result.explain()
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert any(name.endswith(".md") for name in names), names
        assert any("log" in name for name in names), names


@pytest.mark.feature("report.redaction")
def test_report_removes_the_key_the_server_address_and_absolute_paths(
    library_home: UserHome, garden_film: RenderedRun, fake_immich: FakeImmichServer, tmp_path
):
    bundle = tmp_path / "redaction.zip"
    markdown = library_home.run("report", garden_film.run_id).stdout
    data = library_home.run("report", garden_film.run_id, "--json").stdout
    library_home.run("report", garden_film.run_id, "--bundle", str(bundle))
    with zipfile.ZipFile(bundle) as archive:
        members = "\n".join(
            archive.read(name).decode("utf-8", "replace") for name in archive.namelist()
        )

    host = fake_immich.base_url.removeprefix("http://")
    for text in (markdown, data, members):
        assert fake_immich.api_key not in text
        assert host not in text
        assert str(library_home.root) not in text
        assert str(library_home.root.resolve()) not in text


# ── deleting ─────────────────────────────────────────────────────────────────


def _forgotten(home: UserHome, run_id: str) -> bool:
    """The history no longer lists the run, and `runs show` cannot find it."""
    listed = home.run("runs", "list", "--limit", "100").stdout
    shown = home.run("runs", "show", run_id)
    return run_id not in listed and shown.returncode == 1 and "Run not found" in shown.output


@pytest.mark.feature("runs.delete")
def test_runs_delete_removes_the_record_and_its_film(library_home: UserHome, tmp_path):
    run = render(
        library_home, *day_args(QUIET_DAY), "--output", str(tmp_path / "gone.mp4"), into=tmp_path
    )

    result = library_home.run("runs", "delete", run.run_id, "--yes")

    assert result.returncode == 0, result.explain()
    assert not run.film.exists()
    assert _forgotten(library_home, run.run_id)


@pytest.mark.feature("runs.delete")
def test_runs_delete_keep_output_keeps_the_film(library_home: UserHome, tmp_path):
    run = render(
        library_home, *day_args(QUIET_DAY), "--output", str(tmp_path / "kept.mp4"), into=tmp_path
    )

    result = library_home.run("runs", "delete", run.run_id, "--keep-output", "--yes")

    assert result.returncode == 0, result.explain()
    assert run.film.is_file()
    assert _forgotten(library_home, run.run_id)


@pytest.mark.feature("runs.unknown-id-fails")
def test_an_ambiguous_run_prefix_lists_the_matches_and_exits_non_zero(fresh_home: UserHome):
    # A home of its own holding exactly two runs, so what the prefix matches never depends
    # on what other tests left in the session's history.
    home = fresh_home
    film = render(home, *day_args(QUIET_DAY))
    cut = home.run(*day_args(QUIET_DAY), "--no-render", scripted_selection=True)
    assert cut.returncode == 0, cut.explain()
    cut_ids = re.findall(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", cut.output)
    assert cut_ids, cut.explain()
    # The longest prefix both ids share (their date at least): it names neither run alone.
    prefix = os.path.commonprefix([film.run_id, cut_ids[0]])
    assert len(prefix) >= 4, (film.run_id, cut_ids[0])

    shown = home.run("runs", "show", prefix)
    deleted = home.run("runs", "delete", prefix, "--yes")
    listed = home.run("runs", "list", "--limit", "100").stdout

    assert shown.returncode == 1, shown.explain()
    assert "Ambiguous run ID" in shown.output
    assert film.run_id in shown.output and cut_ids[0] in shown.output, shown.explain()
    assert deleted.returncode == 1, deleted.explain()
    assert film.film.is_file()
    assert film.run_id in listed and cut_ids[0] in listed
