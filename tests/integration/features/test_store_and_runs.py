"""What the store keeps: an upgrade from an older release, a rescan, a delivered film, a dead run.

Every test drives the real CLI in a sealed home against the session's fake Immich, and reads
what it left: the printed text, the store's rows, the files on disk, the web server's answer.
"""

from __future__ import annotations

import json
import re
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from tests.e2e.fake_immich import FakeImmichServer
from tests.features.cli_harness import REPO, RUN_ID, UserHome, basic_config, film_facts
from tests.integration.features.library import GARDEN_DAY, QUIET_DAY, day_args
from tests.integration.features.served_ui import free_port, serve_ui

# A SQLite store the published 1.0.0rc5 wheel wrote (schema 0012): two people the scan linked,
# a confirmed relationship, a guessed owner and one saved group. Every person is invented.
_RC5_DUMP = REPO / "tests" / "fixtures" / "rc5_people_store.sql"
_RC5_REVISION = "0012_annotation_assets_is_edited"


@pytest.fixture
def home(tmp_path, fake_immich: FakeImmichServer) -> UserHome:
    home = UserHome(tmp_path / "home")
    home.write_config(basic_config(fake_immich.base_url, fake_immich.api_key, home))
    return home


# ── upgrading a store an older release wrote ─────────────────────────────────


def _rc5_store(home: UserHome) -> Path:
    """The rc.5 store, set as this home's store in its config."""
    path = home.root / "rc5-store.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_RC5_DUMP.read_text())
    config = yaml.safe_load(home.config_path.read_text())
    config["database"] = {"url": f"sqlite:///{path}"}
    home.write_config(config)
    return path


def _rows(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Every row of every table but alembic's own, JSON cells parsed, keyed by table."""
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
            )
        ]
        return {
            table: [
                {key: _cell(row[key]) for key in row.keys()}  # noqa: SIM118 -- sqlite3.Row
                for row in connection.execute(f'SELECT * FROM "{table}"')  # noqa: S608 -- names from sqlite_master
            ]
            for table in tables
        }


def _cell(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _lost(before: dict[str, list[dict]], after: dict[str, list[dict]]) -> list[str]:
    """Each row of the old store that the upgraded one no longer holds, on the old columns."""
    missing = []
    for table, rows in before.items():
        for row in rows:
            if not any(
                all(new.get(column) == value for column, value in row.items())
                for new in after.get(table, [])
            ):
                missing.append(f"{table}: {row}")
    return missing


@pytest.mark.feature("store.migrate")
def test_store_migrate_upgrades_an_rc5_store_to_head_without_a_film_or_a_lost_row(
    home: UserHome,
):
    store = _rc5_store(home)
    before = _rows(store)

    status = home.run("store", "status")
    migrated = home.run("store", "migrate")
    runs = home.run("runs", "list")

    assert sum(len(rows) for rows in before.values()) >= 7, before
    assert f"{_RC5_REVISION} (not at head" in status.stdout, status.explain()
    assert migrated.returncode == 0, migrated.explain()
    assert "(at head)" in migrated.stdout, migrated.explain()
    assert _lost(before, _rows(store)) == []
    # Nothing started a film: no run, no file.
    assert RUN_ID.search(runs.stdout) is None, runs.explain()
    assert not home.videos.exists() or not list(home.videos.rglob("*.mp4"))


@pytest.mark.feature("maintenance.upgrade-keeps-data")
def test_the_first_command_after_an_upgrade_migrates_the_store_and_keeps_everything(
    home: UserHome,
):
    store = _rc5_store(home)
    before = _rows(store)

    people = home.run("people", "show")
    groups = home.run("people", "group", "list")
    status = home.run("store", "status")

    assert people.returncode == 0, people.explain()
    assert "(at head)" in status.stdout, status.explain()
    assert _lost(before, _rows(store)) == []
    for name in ("Ana Example", "Luc Sample"):
        assert name in people.stdout
    assert "pair" in groups.stdout, groups.explain()


@pytest.mark.feature("maintenance.upgrade-keeps-data")
def test_the_upgrade_page_documents_the_rollback():
    page = (REPO / "docs-site" / "docs" / "run" / "maintenance" / "upgrading.md").read_text()
    rollback = page.split("\n## Rollback\n", 1)

    assert len(rollback) == 2
    steps = rollback[1].split("\n## ", 1)[0]
    assert "store restore" in steps
    assert "--from" in steps


# ── a rescan ─────────────────────────────────────────────────────────────────


def _export(home: UserHome, path: Path) -> dict:
    result = home.run("people", "export", "--to", str(path))
    assert result.returncode == 0, result.explain()
    return yaml.safe_load(path.read_text())


def _person(document: dict, person_id: str) -> dict:
    return next(entry for entry in document["people"] if entry["ids"] == [person_id])


@pytest.mark.feature("people.scan-keeps-confirmed")
def test_a_rescan_refreshes_suggestions_and_keeps_roles_relationships_and_groups(
    home: UserHome, tmp_path
):
    first = home.run("people", "scan")
    document = _export(home, tmp_path / "people.yaml")
    robin, kit = _person(document, "person-robin"), _person(document, "person-kit")
    scanned = dict(kit["inferred"]["evidence"])
    # What the owner answered: a role, a note and a relationship, both ways.
    robin["confirmed"] = {
        "role": "parent",
        "notes": "answered by hand",
        "links": [
            {
                "kind": "parent-of",
                "with": "person-kit",
                "reverse": "child-of",
                "decision": "confirmed",
            }
        ],
    }
    kit["confirmed"]["links"] = [
        {
            "kind": "child-of",
            "with": "person-robin",
            "reverse": "parent-of",
            "decision": "confirmed",
        }
    ]
    # A stale suggestion the next scan has to replace.
    kit["inferred"]["evidence"]["count"] = 1
    (tmp_path / "edited.yaml").write_text(yaml.safe_dump(document, sort_keys=False))
    imported = home.run("people", "import", "--from", str(tmp_path / "edited.yaml"), "--replace")
    grouped = home.run("people", "group", "add", "parent-and-child", '"Robin" AND "Kit"')

    rescan = home.run("people", "scan")
    after = _export(home, tmp_path / "after.yaml")
    groups = home.run("people", "group", "list")

    assert first.returncode == 0, first.explain()
    assert imported.returncode == 0, imported.explain()
    assert grouped.returncode == 0, grouped.explain()
    assert rescan.returncode == 0, rescan.explain()
    assert _person(after, "person-kit")["inferred"]["evidence"] == scanned
    robin_after = _person(after, "person-robin")["confirmed"]
    assert robin_after["role"] == "parent"
    assert robin_after["notes"] == "answered by hand"
    assert [(link["kind"], link["with"]) for link in robin_after["links"]] == [
        ("parent-of", "person-kit")
    ]
    assert [
        (link["kind"], link["with"]) for link in _person(after, "person-kit")["confirmed"]["links"]
    ] == [("child-of", "person-robin")]
    assert "parent-and-child" in groups.stdout, groups.explain()


# ── delivery ─────────────────────────────────────────────────────────────────


@pytest.mark.feature("upload.reclaims-local-copy")
def test_a_delivered_film_is_removed_locally_and_the_run_keeps_its_record_and_immich_link(
    library_home: UserHome, fake_immich: FakeImmichServer, tmp_path
):
    uploads_before = len(fake_immich.uploads)
    output = tmp_path / "delivered.mp4"

    result = library_home.run(
        *day_args(QUIET_DAY),
        "--upload-to-immich",
        "--output",
        str(output),
        scripted_selection=True,
    )
    run_id = RUN_ID.search(result.output)
    shown = library_home.run("runs", "show", run_id.group(0)) if run_id else None

    assert result.returncode == 0, result.explain()
    assert run_id, result.explain()
    assert len(fake_immich.uploads) == uploads_before + 1
    # The film Immich got is a real film, and the local copy is gone.
    sent = tmp_path / "sent.mp4"
    sent.write_bytes(fake_immich.uploads[-1].data)
    assert film_facts(sent).duration > 0.5
    assert list(tmp_path.rglob("delivered*.mp4")) == []
    assert shown is not None and shown.returncode == 0, shown and shown.explain()
    assert re.search(r"Immich\s*│\s*delivered", shown.stdout), shown.explain()
    assert "removed after delivery to Immich" in shown.stdout
    link = re.search(r"Immich Link\s*│\s*(\S+)", shown.stdout)
    assert link and link.group(1).startswith(fake_immich.base_url), shown.explain()
    assert f"uploaded-{uploads_before + 1}" in link.group(1)


# ── a run whose process died ─────────────────────────────────────────────────

# The scripted selection with slow stages, so a run is still going when the test looks.
_SLOW_SELECTION = """
import sys
from tests.e2e.fake_editorial import install_fake_editorial_route

install_fake_editorial_route(stage_seconds=3.0)

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[1:]]
main()
"""


def _start_slow_cut(home: UserHome) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 -- our own CLI, fixed argv
        [sys.executable, "-c", _SLOW_SELECTION, *day_args(GARDEN_DAY), "--no-render"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=home.env(),
        cwd=home.root,
    )


def _running_run(home: UserHome, child: subprocess.Popen) -> str:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        assert child.poll() is None, "the cut ended before the test saw it running"
        listed = home.run("runs", "list", "--status", "running")
        if found := RUN_ID.search(listed.stdout):
            return found.group(0)
        time.sleep(0.5)
    raise AssertionError("no running run appeared")


@pytest.mark.feature("runs.interrupted")
def test_a_run_whose_process_died_reads_interrupted_and_a_live_one_stays_running(
    home: UserHome,
):
    child = _start_slow_cut(home)
    try:
        run_id = _running_run(home, child)
        # Read twice while its owner is alive: neither read may end it.
        alive_list = home.run("runs", "list")
        alive_show = home.run("runs", "show", run_id)
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)

    dead_list = home.run("runs", "list")
    dead_show = home.run("runs", "show", run_id)
    port = free_port()
    with serve_ui(home, "ui", "--port", str(port), port=port):
        served = httpx.get(f"http://127.0.0.1:{port}/api/v1/runs/{run_id}", timeout=30)

    assert re.search(rf"{run_id}.*running", alive_list.stdout), alive_list.explain()
    assert re.search(r"Status\s*│\s*running", alive_show.stdout), alive_show.explain()
    assert re.search(rf"{run_id}.*interrupted", dead_list.stdout), dead_list.explain()
    assert re.search(r"Status\s*│\s*interrupted", dead_show.stdout), dead_show.explain()
    assert served.status_code == 200, served.text
    assert served.json()["status"] == "interrupted"
