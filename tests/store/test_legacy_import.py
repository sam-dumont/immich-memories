"""The legacy import as a whole: every domain, resumable, recorded, verified, run once at start."""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from click.testing import CliRunner

from immich_memories.analysis.editorial_shareability import OWNER_SOURCE
from immich_memories.config_loader import Config, set_config
from immich_memories.db import StoreLocation, close_stores, open_store
from immich_memories.db.inventory import digests
from immich_memories.db.legacy_import import read_import_record
from immich_memories.db.tables import asset_flags
from immich_memories.people.transfer import export_yaml
from immich_memories.store.legacy_imports import (
    IMPORT_FROM_ENV,
    enable_first_open_import,
    run_import,
    verify_import,
)

from .backends import drop_schema, pg_url
from .legacy_home import HOLD, snapshot, write_legacy_home

CLEAN = {"people": [], "annotations": [], "operations": [], "banks": []}


def _default_cache_config() -> None:
    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)


@pytest.fixture
def home(tmp_path) -> Iterator[Path]:
    """A legacy home whose config keeps the default cache locations beside it."""
    _default_cache_config()
    yield write_legacy_home(tmp_path / "home")
    set_config(None)


@pytest.fixture
def sibling(location) -> Iterator[StoreLocation]:
    """A second, empty store on the same backend."""
    if location.dialect_name == "sqlite":
        yield StoreLocation(url=location.url.replace("store.db", "sibling.db"))
        return
    schema = f"test_{uuid.uuid4().hex[:12]}"
    yield StoreLocation(url=location.url, schema=schema)
    close_stores()
    drop_schema(pg_url(), schema)


def _content(store) -> dict[str, object]:
    # The import records and the registry header carry the time they were written; the
    # registry is compared as the document it holds, everything else row for row.
    with store.connect() as connection:
        rows = {
            name: value
            for name, value in digests(connection).items()
            if name not in {"store_meta", "people_registry"}
        }
    return {**rows, "people": export_yaml(store)}


def test_the_import_brings_every_domain_in_and_records_it(store, home):
    before = snapshot(home)

    outcomes = run_import(store, home)

    assert [outcome.imported > 0 for outcome in outcomes] == [True, True, True, True]
    assert verify_import(store, home) == CLEAN
    with store.connect() as connection:
        record = read_import_record(connection)
    assert record["home"] == str(home)
    assert set(record["importers"]) == set(CLEAN)
    assert snapshot(home) == before


def test_a_second_import_skips_every_importer_whose_files_are_unchanged(store, home):
    run_import(store, home)
    first = _content(store)

    again = run_import(store, home)

    assert all(outcome.imported == 0 for outcome in again)
    assert all(outcome.notes[0].startswith("unchanged since") for outcome in again)
    assert _content(store) == first


def test_a_changed_file_reruns_its_importer_only(store, home):
    run_import(store, home)
    document = yaml.safe_load((home / "people.yaml").read_text())
    document["people"].append({"ids": ["id-new"], "name": "New Example"})
    (home / "people.yaml").write_text(yaml.dump(document, sort_keys=False))

    people, *others = run_import(store, home)

    assert people.imported == 1
    assert all(outcome.notes[0].startswith("unchanged since") for outcome in others)


def test_verify_names_an_owner_decision_the_store_holds_differently(store, home):
    run_import(store, home)
    with store.begin() as connection:
        connection.execute(
            sa.update(asset_flags)
            .where(asset_flags.c.source == OWNER_SOURCE)
            .values(evidence='{"via": "cli"}')
        )

    problems = verify_import(store, home)

    assert problems["annotations"] == ["asset_flags still-1/cleared_family/owner: evidence differ"]
    assert problems["people"] == problems["operations"] == problems["banks"] == []


def _import_and_die(url: str, schema: str, home: str, die_at: int) -> None:
    """Run the import in a child and SIGKILL it inside the annotations, after some batches."""
    _default_cache_config()
    from immich_memories.store import legacy_annotations

    real = legacy_annotations.upsert_rows
    calls = 0

    def dying(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == die_at:
            os.kill(os.getpid(), signal.SIGKILL)
        return real(*args, **kwargs)

    legacy_annotations.upsert_rows = dying
    run_import(open_store(location=StoreLocation(url=url, schema=schema)), Path(home))


def test_an_interrupted_import_finishes_on_rerun_and_matches_a_clean_one(
    location, sibling, tmp_path
):
    _default_cache_config()
    home = write_legacy_home(tmp_path / "home", extra_descriptions=2500)
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_import_and_die, args=(location.url, location.schema, str(home), 3)
    )
    child.start()
    child.join(timeout=120)
    assert child.exitcode == -signal.SIGKILL

    interrupted = open_store(location=location)
    with interrupted.connect() as connection:
        assert read_import_record(connection) is None
    run_import(interrupted, home)
    clean = open_store(location=sibling)
    run_import(clean, home)

    assert _content(interrupted) == _content(clean)
    assert verify_import(interrupted, home) == CLEAN
    set_config(None)


def test_the_first_open_imports_once_and_later_opens_only_read_the_record(
    location, home, monkeypatch, caplog
):
    monkeypatch.setenv(IMPORT_FROM_ENV, str(home))
    before = snapshot(home)
    enable_first_open_import()

    with caplog.at_level(logging.INFO, logger="immich_memories.store.legacy_imports"):
        store = open_store(location=location)
        close_stores()
        open_store(location=location)

    started = [r for r in caplog.records if r.getMessage().startswith("Importing the legacy")]
    assert len(started) == 1
    assert verify_import(store, home) == CLEAN
    assert snapshot(home) == before


def test_without_legacy_files_the_first_open_records_nothing(location, tmp_path, monkeypatch):
    _default_cache_config()
    monkeypatch.setenv(IMPORT_FROM_ENV, str(tmp_path / "empty"))
    enable_first_open_import()

    store = open_store(location=location)

    with store.connect() as connection:
        assert read_import_record(connection) is None
    set_config(None)


def _start_the_app(url: str, schema: str, home: str) -> bool:
    """One process starting up: the hook the CLI enables, then the store's first open."""
    os.environ[IMPORT_FROM_ENV] = home
    _default_cache_config()
    started: list[str] = []

    class Seen(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            started.append(record.getMessage())

    log = logging.getLogger("immich_memories.store.legacy_imports")
    log.setLevel(logging.INFO)
    log.addHandler(Seen())
    enable_first_open_import()
    open_store(location=StoreLocation(url=url, schema=schema))
    return any(message.startswith("Importing the legacy") for message in started)


def test_two_processes_starting_together_import_once(location, home):
    context = multiprocessing.get_context("spawn")
    with context.Pool(2) as pool:
        ran = pool.starmap(_start_the_app, [(location.url, location.schema, str(home))] * 2)

    assert sorted(ran) == [False, True]
    store = open_store(location=location)
    assert verify_import(store, home) == CLEAN


def test_the_cli_imports_verifies_and_fails_on_a_difference(location, home, monkeypatch):
    from immich_memories.cli import main

    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)
    runner = CliRunner()

    first = runner.invoke(main, ["store", "import", "--from", str(home), "--verify"])
    assert first.exit_code == 0, first.output
    assert "Every legacy record is in the store" in first.output

    (home / "special-days.json").write_text("[]")
    second = runner.invoke(main, ["store", "import", "--from", str(home), "--verify"])
    assert second.exit_code == 1
    assert "special_days: the catalogue differs from special-days.json" in second.output


def test_the_config_names_where_the_import_looks_when_the_environment_does_not(
    tmp_path, monkeypatch
):
    from immich_memories.store.legacy_imports import legacy_home

    monkeypatch.delenv(IMPORT_FROM_ENV)
    config = Config()
    config.database.import_from = str(tmp_path / "old-install")
    set_config(config)
    try:
        assert legacy_home() == tmp_path / "old-install"
        monkeypatch.setenv(IMPORT_FROM_ENV, str(tmp_path / "mounted"))
        assert legacy_home() == tmp_path / "mounted"
    finally:
        set_config(None)


def test_verify_accepts_a_stricter_hold_and_names_a_looser_one(store, home):
    from immich_memories.db.tables import audience_holds

    run_import(store, home)

    def hold(verdict: str) -> None:
        with store.begin() as connection:
            connection.execute(sa.update(audience_holds).values(hold={**HOLD, "verdict": verdict}))

    hold("do_not_show")
    assert verify_import(store, home)["banks"] == []
    hold("share")
    assert verify_import(store, home)["banks"] == [
        "audience_holds still-1/text: looser than the legacy hold"
    ]


def test_verify_names_an_owner_edit_the_store_holds_differently(store, home):
    from immich_memories.db.tables import owner_edits

    run_import(store, home)
    with store.begin() as connection:
        connection.execute(sa.update(owner_edits).values(record={"version": "changed"}))

    assert verify_import(store, home)["banks"] == ["owner_edits 1234abcd: record differ"]


def test_the_replay_harness_fingerprints_the_imported_banks_in_the_store(
    store, location, home, monkeypatch
):
    """The parity harness reads the store the replayed CLI reads, on either backend: what
    the legacy judgment files and vote banks held is what it counts after the import."""
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "replay_editorial_routes.py"
    spec = importlib.util.spec_from_file_location("replay_editorial_routes", script)
    harness = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = harness
    spec.loader.exec_module(harness)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)
    assert harness.bank_rows() == 0

    run_import(store, home)

    fingerprint = harness.store_fingerprint()
    # question-a, question-b (judgments.db; annotations.sqlite repeats question-a),
    # one Cull verdict, one episode reading, one block vote and one row vote.
    assert {name: rows for name, (rows, _) in fingerprint.items() if rows} == {
        "judgments": 2,
        "editorial_verdicts": 1,
        "editorial_episode_readings": 1,
        "vote_bank_entries": 2,
    }


def test_a_key_two_files_hold_is_verified_against_the_one_the_import_kept(store, home):
    import sqlite3
    from contextlib import closing

    # annotations.sqlite and judgments.db both answered question-a, at different times.
    with closing(sqlite3.connect(home / "cache" / "judgments.db")) as legacy, legacy:
        legacy.execute(
            "UPDATE judgments SET answered_at = '2020-01-01 00:00:00' WHERE key = 'question-a'"
        )
    run_import(store, home)

    assert verify_import(store, home)["annotations"] == []
