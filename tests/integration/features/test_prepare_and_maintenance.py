"""Preparing a scope ahead of a film, and the caches and state an install keeps on disk.

`prepare` and the person film run through the real Basic editor (`real_editor.py`): Basic's
classifiers have no hermetic model, so the child prepares at `metadata_only` and still runs
the preview, pixel and face producers a cut banks. Each test has a fake Immich of its own,
so what it asked the server for is its own. What the tests read is what a user gets: the
printed table, the exit code, the rows the store kept, the web server's cache figures and the
files left in the home.
"""

from __future__ import annotations

import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import yaml

from immich_memories.analysis.audience.exposure_chains import runs_holding
from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import ALL_PICTURES
from tests.features.cli_harness import OutboundTrap, UserHome, basic_config, films_under
from tests.integration.features.library import DEPARTURE_DAY, QUIET_DAY, day_args, render
from tests.integration.features.real_editor import home_on, run
from tests.integration.features.served_ui import free_port, serve_ui

pytestmark = pytest.mark.fake_immich_only(
    "reads what its own fake Immich was asked for, or swaps a preview it serves"
)

# A week of the fixture library before the trip: one household, a few people per day.
_WEEK_START, _WEEK_END = "2025-07-01", "2025-07-07"
# Kit is in the household's pictures every day of the first eleven days.
_PERSON, _PERSON_START, _PERSON_END = "Kit", "2025-07-01", "2025-07-11"
_PREPARING = re.compile(r"Preparing (\d+) pictures over \d+ window")
_CANDIDATES = re.compile(r"Candidates: (\d+) video, (\d+) photo")


@pytest.fixture
def home(tmp_path: Path, delivery_immich: FakeImmichServer, outbound_trap: OutboundTrap):
    return home_on(tmp_path / "home", delivery_immich, outbound_trap.env())


def _store(home: UserHome) -> Path:
    return home.root / ".immich-memories" / "store.db"


def _prepared_ids(home: UserHome) -> set[str]:
    """The pictures the store holds pixel facts for: what preparation measured."""
    with sqlite3.connect(_store(home)) as connection:
        return {row[0] for row in connection.execute("SELECT DISTINCT asset_id FROM pixel_facts")}


def _candidates(home: UserHome, *scope: str) -> int:
    """How many pictures `generate --dry-run` finds in a scope."""
    result = run(home, "generate", *scope, "--include-photos", "--dry-run")
    assert result.returncode == 0, result.explain()
    found = _CANDIDATES.search(result.output)
    assert found, result.explain()
    return int(found.group(1)) + int(found.group(2))


def _seconds(said: str) -> float:
    """A duration `human_duration` printed ("81 s", "42 min", "2 h 15 min"), in seconds."""
    hours = re.search(r"(\d+) h", said)
    minutes = re.search(r"(\d+) min", said)
    seconds = re.fullmatch(r"(\d+) s", said.strip())
    if seconds:
        return float(seconds.group(1))
    return 3600.0 * int(hours.group(1) if hours else 0) + 60.0 * int(
        minutes.group(1) if minutes else 0
    )


@contextmanager
def _unreadable_preview(server: FakeImmichServer, asset_id: str, junk: Path) -> Iterator[None]:
    """Serve bytes no image decoder reads as this asset's preview until the block ends."""
    # The preview map is the session's own (a test server borrows its media), so it is put back.
    previews = server._thumbnail_paths  # noqa: SLF001 -- the fake's served previews, by id
    junk.write_bytes(b"not a picture")
    before = previews[asset_id]
    previews[asset_id] = junk
    try:
        yield
    finally:
        previews[asset_id] = before


# ── prepare: scope, cost, and what is still missing ──────────────────────────


@pytest.mark.feature("prepare.scope-and-cost")
def test_prepare_takes_generate_s_scope_and_prints_each_producer_s_rate_and_a_projection(
    home: UserHome,
):
    library_size = 1_000_000
    week = ("--start", _WEEK_START, "--period", "1w")

    result = run(home, "prepare", *week, "--library-size", str(library_size))

    assert result.returncode == 0, result.explain()
    preparing = _PREPARING.search(result.output)
    assert preparing, result.explain()
    # The same scope generate reads: --start with --period, and --start with --end.
    assert int(preparing.group(1)) == _candidates(home, *week)
    assert int(preparing.group(1)) == _candidates(home, "--start", _WEEK_START, "--end", _WEEK_END)
    rows = dict(
        re.findall(r"^(\w+)\s+\d+\s+(\d+\.\d{4})\s+[\d.]+%\s+\S+ (?:s|min|h)", result.output, re.M)
    )
    assert {"previews", "pixels", "faces", "total"} <= set(rows), result.explain()
    total = float(rows["total"])
    assert total == pytest.approx(sum(float(v) for k, v in rows.items() if k != "total"), abs=4e-4)
    projected = re.search(r"At this rate 1,000,000 pictures would take (.+)\.", result.output)
    assert projected, result.explain()
    # The projection is the total rate times the size, within the printed rate's rounding.
    assert _seconds(projected.group(1)) == pytest.approx(
        total * library_size, abs=0.00005 * library_size + 60
    )


@pytest.mark.feature("prepare.scope-and-cost")
def test_prepare_exits_one_naming_the_missing_producer_and_a_rerun_finishes_the_scope(
    home: UserHome, delivery_immich: FakeImmichServer, tmp_path: Path
):
    day = ("--start", QUIET_DAY, "--end", QUIET_DAY)
    # An unedited still: an edited one's preview is Immich's editor render, served under its own name.
    victim = next(
        p for p in ALL_PICTURES if p.day == QUIET_DAY and p.kind == "still" and not p.edited
    )

    with _unreadable_preview(delivery_immich, victim.asset_id, tmp_path / "junk.jpg"):
        failed = run(home, "prepare", *day)
    after_failure = _prepared_ids(home)
    resumed = run(home, "prepare", *day)

    assert failed.returncode == 1, failed.explain()
    assert f"preview:{victim.asset_id}" in failed.output
    assert re.search(r"Still missing after this pass — .*pixel:[\w-]+: 1", failed.output), (
        failed.explain()
    )
    assert victim.asset_id not in after_failure
    # The rerun resumes only what is missing: the one preview and its pixel facts.
    assert re.search(r"^pixels\s+1\s", resumed.output, re.M), resumed.explain()
    assert resumed.returncode == 0, resumed.explain()
    assert "Still missing" not in resumed.output
    assert victim.asset_id in _prepared_ids(home)


# ── generate prepares what its film can reach, and banks it ──────────────────


def _taken(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@pytest.mark.feature("generate.prepares-only-reachable-pictures")
def test_a_person_film_prepares_that_person_s_pictures_and_their_bursts_and_a_recut_reuses_them(
    home: UserHome, delivery_immich: FakeImmichServer
):
    scope = ("--start", _PERSON_START, "--end", _PERSON_END)
    cut = ("generate", "--person", _PERSON, *scope, "--include-photos", "--no-music", "--quiet")
    window = [p for p in ALL_PICTURES if _PERSON_START <= p.day <= _PERSON_END]
    pictured = {p.asset_id for p in window if _PERSON in p.people}
    # The bursts around a demanded picture decide whether the exposure rule holds it.
    reachable = runs_holding(((p.asset_id, _taken(p.taken_at)) for p in window), pictured)

    first = run(home, *cut, "--no-render")
    prepared = _prepared_ids(home)
    previews_asked = _preview_requests(delivery_immich)
    second = run(home, *cut, "--no-render")
    whole_window = run(home, "generate", *scope, "--include-photos", "--dry-run")

    assert first.returncode == 0, first.explain()
    assert pictured <= prepared
    assert prepared <= reachable, sorted(prepared - reachable)
    assert len(prepared) < len(window) / 2, (len(prepared), len(window))
    # The rest of the window stays unprepared, and the dry run says so.
    assert re.search(
        r"Preparation: \d+ of \d+ pictures in this period aren't prepared yet",
        (whole_window.output),
    ), whole_window.explain()
    # A second cut over the same pictures reuses the banked facts and their cached previews.
    assert second.returncode == 0, second.explain()
    assert _preview_requests(delivery_immich) == previews_asked
    assert _prepared_ids(home) == prepared


# An edited picture's preview is always fetched fresh: its cached file may be an earlier run's
# unedited render (#2114). Every other preview a cut reads once comes from the cache.
_EDITED = {p.asset_id for p in ALL_PICTURES if p.edited}


def _preview_requests(server: FakeImmichServer) -> int:
    return sum(
        1
        for method, path in server.wire.requests
        if method == "GET"
        and path.startswith("/api/assets/")
        and path.endswith("/thumbnail")
        and path.split("/")[3] not in _EDITED
    )


# ── caches: cleared without losing anything, and sized by the pictures ──────


def _caches(port: int) -> dict[str, dict]:
    answer = httpx.get(f"http://127.0.0.1:{port}/api/v1/caches", timeout=30)
    assert answer.status_code == 200, answer.text
    return {row["name"]: row for row in answer.json()}


@pytest.mark.feature("maintenance.caches")
def test_clearing_the_caches_keeps_films_runs_people_and_prepared_facts(home: UserHome):
    first = run(home, "prepare", "--start", QUIET_DAY, "--end", QUIET_DAY)
    after_one_day = len(
        list((home.root / ".immich-memories" / "cache" / "thumbnails").rglob("*.jpg"))
    )
    second = run(home, "prepare", "--start", DEPARTURE_DAY, "--end", DEPARTURE_DAY)
    film = render(home, *day_args(DEPARTURE_DAY))
    runs_before = home.run("runs", "list", "--limit", "50").stdout
    people_before = home.run("people", "list").stdout
    port = free_port()
    home.turn_sign_in_off()  # this test is about the caches, not sign-in

    with serve_ui(home, "ui", "--host", "127.0.0.1", "--port", str(port), port=port):
        filled = _caches(port)
        cleared = {
            name: httpx.post(f"http://127.0.0.1:{port}/api/v1/caches/{name}/clear", timeout=30)
            for name in ("video", "thumbnail", "prepared_source")
        }
        emptied = _caches(port)
    runs_after = home.run("runs", "list", "--limit", "50").stdout
    people_after = home.run("people", "list").stdout
    dry_run = run(home, "generate", *day_args(DEPARTURE_DAY)[1:], "--dry-run")
    rerendered = home.run("runs", "render", film.run_id, scripted_selection=True)

    assert first.returncode == second.returncode == 0, (first.explain(), second.explain())
    # The preview cache holds one preview per picture a scope reached, and grows with them.
    one_day = sum(1 for p in ALL_PICTURES if p.day == QUIET_DAY)
    two_days = one_day + sum(1 for p in ALL_PICTURES if p.day == DEPARTURE_DAY)
    assert after_one_day >= one_day
    assert filled["thumbnail"]["items"] >= two_days > after_one_day
    assert filled["video"]["items"] >= 1, filled
    # The render banked what it prepared, so a re-render would prepare nothing twice.
    assert filled["prepared_source"]["items"] >= 1, filled
    assert filled["prepared_source"]["bytes"] > 0, filled
    assert all(answer.status_code == 200 for answer in cleared.values()), cleared
    assert cleared["thumbnail"].json()["removed"] == filled["thumbnail"]["items"]
    assert cleared["prepared_source"].json()["removed"] == filled["prepared_source"]["items"]
    assert all(emptied[name]["items"] == 0 for name in cleared), emptied
    # Nothing the user keeps lived in a cache.
    assert film.film.is_file()
    assert runs_after == runs_before
    assert people_after == people_before
    assert "Preparation: all " in dry_run.output, dry_run.explain()
    # The saved cut renders again; its clip is fetched once more.
    assert rerendered.returncode == 0, rerendered.explain()
    assert len(films_under(home.videos)) == 2


# ── stop, reset and remove: the native install ───────────────────────────────


def _app_owned(home: UserHome) -> set[str]:
    """Every top-level entry the app left in the home, besides the test's own files."""
    return {entry.name for entry in home.root.iterdir() if not entry.name.startswith("ui-")}


def _stop_with_ctrl_c(home: UserHome, port: int) -> tuple[int, str]:
    """`immich-memories ui` started, then stopped the way a terminal stops it.

    Stopped as soon as it answers, while the answers it starts behind the pages (suggestions,
    this year's and last year's trips) are still being worked out. Returns the exit code and
    what the process printed, so an abort says where it happened.
    """
    log = home.root / f"ui-{port}-ctrl-c.log"
    with log.open("w") as sink:
        server = subprocess.Popen(  # noqa: S603 -- our own CLI, fixed argv
            [sys.executable, "-m", "immich_memories.cli", "ui", "--port", str(port)],
            env={**home.env(), "PYTHONFAULTHANDLER": "1"},
            cwd=home.root,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_live(port, server)
        server.send_signal(signal.SIGINT)
        return server.wait(timeout=30), log.read_text(errors="replace")
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=5)


def _wait_live(port: int, server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        assert server.poll() is None, f"ui exited {server.returncode}"
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health/live", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError("ui never answered")


@pytest.mark.feature("maintenance.lifecycle")
def test_a_native_install_stops_keeping_everything_resets_aside_and_removes_completely(
    tmp_path: Path, delivery_immich: FakeImmichServer, outbound_trap: OutboundTrap
):
    home = UserHome(tmp_path / "home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(delivery_immich.base_url, delivery_immich.api_key, home))
    state, backup = home.root / ".immich-memories", home.root / ".immich-memories.before-reset"
    film = render(home, *day_args(QUIET_DAY))
    runs = home.run("runs", "list", "--limit", "50").stdout

    # 1. Stop the app: Ctrl-C in the terminal running `ui`, then start it again.
    stopped, stop_output = _stop_with_ctrl_c(home, free_port())
    port = free_port()
    home.turn_sign_in_off()  # this test is about the install's data, not sign-in
    with serve_ui(home, "ui", "--port", str(port), port=port):
        listed = httpx.get(f"http://127.0.0.1:{port}/api/v1/runs", timeout=30)

    # 2. Remove the app keeping data: everything it keeps is in the two documented places.
    owned = _app_owned(home)

    # 3. Reset for a fresh trial: move the state aside, a new config with `tier: basic`.
    state.rename(backup)
    state.mkdir(mode=0o700)
    home.write_config(basic_config(delivery_immich.base_url, delivery_immich.api_key, home))
    fresh_runs = home.run("runs", "list", "--limit", "50")
    tier = home.run("config", "show")
    old_runs = home.run(
        "runs",
        "list",
        "--limit",
        "50",
        env={"IMMICH_MEMORIES_DATABASE_URL": f"sqlite:///{backup / 'store.db'}"},
    )

    # 4. Remove everything the app owns locally.
    shutil.rmtree(state)
    shutil.rmtree(backup)
    shutil.rmtree(home.videos)
    left = _app_owned(home)

    assert stopped in (0, -signal.SIGINT, 130), f"exit {stopped}:\n{stop_output[-4000:]}"
    assert listed.status_code == 200, listed.text
    assert film.run_id in listed.text
    assert film.run_id in runs
    assert owned == {".immich-memories", "Videos"}, owned
    assert film.film.is_relative_to(home.videos)
    assert fresh_runs.returncode == 0, fresh_runs.explain()
    assert film.run_id not in fresh_runs.stdout
    assert re.search(r"│ tier\s+│ basic\s+│", tier.stdout), tier.explain()
    assert film.run_id in old_runs.stdout, old_runs.explain()
    assert left == set(), left
    # Immich keeps every picture: nothing in it was deleted, and it still serves the library.
    assert not [r for r in delivery_immich.wire.requests if r[0] == "DELETE"]
    assert (
        httpx.get(
            f"{delivery_immich.base_url}/api/server/version",
            headers={"x-api-key": delivery_immich.api_key},
            timeout=30,
        ).status_code
        == 200
    )


def _config_tier(home: UserHome) -> str:
    return yaml.safe_load(home.config_path.read_text())["tier"]
