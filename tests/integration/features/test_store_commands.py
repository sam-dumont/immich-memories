"""The store commands a self-hoster runs by hand: copy, import from an older install, facts.

Each test drives the real CLI in a sealed home and reads back what it left: the printed text,
the exit code, and what the commands that read the store (`runs list`, `people list`,
`store facts status`) answer afterwards. The PostgreSQL side of `store copy` runs in
`tests/store/test_store_on_postgresql.py`, where `make test-store` gives it a server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from immich_memories.analysis.editorial_preparation_detectors import (
    MARQO_HEAD,
    MARQO_ONNX_ID,
    MARQO_STILL_EQUIVALENT,
    MARQO_VERSION,
)
from immich_memories.cache.embedding_cache import HeadFactStore
from immich_memories.db import StoreLocation, close_stores, open_store
from immich_memories.triage.heads import HeadFact
from tests.e2e.fake_library import ALL_PICTURES
from tests.features.cli_harness import OutboundTrap, UserHome
from tests.integration.features.library import QUIET_DAY, RenderedRun, day_args, render
from tests.integration.features.real_editor import home_on, run
from tests.store.legacy_home import snapshot, write_legacy_home

# The run, people and catalogue day the legacy home holds (tests/store/legacy_home.py).
_LEGACY_RUN = "20240301_080000_ab12"


def _env_on(store: Path) -> dict[str, str]:
    return {"IMMICH_MEMORIES_DATABASE_URL": f"sqlite:///{store}"}


def _reads(home: UserHome, env: dict[str, str] | None = None) -> dict[str, str]:
    """What the commands that read the store print: the history and the people."""
    return {
        "runs": home.run("runs", "list", "--limit", "200", env=env).stdout,
        "people": home.run("people", "list", env=env).stdout,
    }


# ── store copy ───────────────────────────────────────────────────────────────


@pytest.fixture
def used_home(fresh_home: UserHome) -> tuple[UserHome, RenderedRun]:
    """A home that made a film and keeps a household: a store with real rows in it."""
    film = render(fresh_home, *day_args(QUIET_DAY))
    return fresh_home, film


@pytest.mark.feature("store.copy")
def test_store_copy_moves_every_table_and_the_copy_answers_like_the_original(
    used_home: tuple[UserHome, RenderedRun], tmp_path: Path
):
    home, film = used_home
    target = tmp_path / "moved" / "store.db"
    target.parent.mkdir()
    before = _reads(home)

    copied = home.run("store", "copy", "--to", f"sqlite:///{target}")
    after = _reads(home, _env_on(target))
    refused = home.run("store", "copy", "--to", f"sqlite:///{target}")
    forced = home.run("store", "copy", "--to", f"sqlite:///{target}", "--force")
    into_itself = home.run("store", "copy", "--to", f"sqlite:///{target}", env=_env_on(target))

    assert copied.returncode == 0, copied.explain()
    assert "every table matches" in " ".join(copied.stdout.split())
    rows = dict(re.findall(r"^\s+(\w+)\s+(\d+)$", copied.stdout, re.M))
    assert int(rows["pipeline_runs"]) >= 1, copied.explain()
    # Pointed at the copy, the app answers exactly as it did on the original.
    assert after == before
    assert film.run_id in after["runs"]
    assert refused.returncode == 1, refused.explain()
    assert "--force" in refused.output
    assert forced.returncode == 0, forced.explain()
    assert into_itself.returncode == 1, into_itself.explain()
    assert "the target is the store itself" in into_itself.output


# ── store import ─────────────────────────────────────────────────────────────


@pytest.mark.feature("store.import")
def test_store_import_brings_an_older_install_s_files_in_verifies_them_and_never_changes_them(
    fresh_home: UserHome, tmp_path: Path
):
    old = write_legacy_home(tmp_path / "old" / "immich-memories")
    untouched = snapshot(old)

    imported = fresh_home.run("store", "import", "--from", str(old), "--verify")
    again = fresh_home.run("store", "import", "--from", str(old), "--verify")
    reads = _reads(fresh_home)
    people = fresh_home.run("people", "export")

    assert imported.returncode == 0, imported.explain()
    assert re.search(r"\d+ imported", imported.stdout), imported.explain()
    assert "Every legacy record is in the store" in imported.stdout
    assert re.findall(r"^\s+(\w+): verified$", imported.stdout, re.M), imported.explain()
    # The old history and people now come from the store.
    assert _LEGACY_RUN in reads["runs"], reads["runs"]
    assert "Alex Example" in people.stdout, people.explain()
    # Safe to run again: nothing new, nothing replaced, still verified.
    assert again.returncode == 0, again.explain()
    assert not re.search(r"[1-9]\d* imported", again.stdout), again.explain()
    assert "Every legacy record is in the store" in again.stdout
    # The legacy files are only read.
    assert snapshot(old) == untouched


@pytest.mark.feature("store.import")
def test_store_import_verify_exits_one_naming_a_record_the_store_lost(
    fresh_home: UserHome, tmp_path: Path
):
    old = write_legacy_home(tmp_path / "old" / "immich-memories")
    assert fresh_home.run("store", "import", "--from", str(old)).returncode == 0
    deleted = fresh_home.run("runs", "delete", _LEGACY_RUN, "--yes")

    verified = fresh_home.run("store", "import", "--from", str(old), "--verify")

    assert deleted.returncode == 0, deleted.explain()
    # A record already imported once is never re-imported, so the loss shows up as a difference.
    assert verified.returncode == 1, verified.explain()
    assert re.search(r"\w+: \d+ differences", verified.stdout), verified.explain()
    assert "Every legacy record is in the store" not in verified.stdout


# ── store facts ──────────────────────────────────────────────────────────────


@pytest.fixture
def prepared_home(tmp_path: Path, delivery_immich, outbound_trap: OutboundTrap) -> UserHome:
    """A home whose store knows one day of the library, as a real preparation left it."""
    home = home_on(tmp_path / "home", delivery_immich, outbound_trap.env())
    prepared = run(home, "prepare", "--start", QUIET_DAY, "--end", QUIET_DAY)
    assert prepared.returncode == 0, prepared.explain()
    return home


def _bank(home: UserHome, rows: dict[str, list[HeadFact]], encoder: str) -> None:
    """Detector answers banked the way preparation banks them, into the home's own store."""
    # WHY: the hermetic install has no detector models; these rows stand in for their answers.
    store = open_store(
        location=StoreLocation(url=f"sqlite:///{home.root / '.immich-memories' / 'store.db'}")
    )
    try:
        HeadFactStore(store).remember_facts(rows, encoder_key=encoder)
    finally:
        close_stores()


def _status(home: UserHome) -> dict[tuple[str, str, str], int]:
    result = home.run("store", "facts", "status", "--json")
    assert result.returncode == 0, result.explain()
    report = json.loads(result.stdout)
    assert report["contract"] == "detector-facts-v1"
    return {(r["head"], r["version"], r["state"]): r["facts"] for r in report["rows"]}


@pytest.mark.feature("store.facts")
@pytest.mark.fake_immich_only("prepares a day on a fake Immich of its own")
def test_store_facts_reports_versions_migrates_compatible_stills_and_refreshes_only_what_is_named(
    prepared_home: UserHome,
):
    home = prepared_home
    stills = sorted(p.asset_id for p in ALL_PICTURES if p.day == QUIET_DAY and p.kind == "still")
    chosen, kept = stills[0], stills[1:]
    old_answer = HeadFact(MARQO_HEAD, "no", 0.2, MARQO_STILL_EQUIVALENT)
    _bank(home, {asset_id: [old_answer] for asset_id in stills}, MARQO_ONNX_ID)
    _bank(home, {chosen: [HeadFact("doc_docling", "photograph", 0.9, "det-v2")]}, "docling")

    shown = home.run("store", "facts", "status")
    before = _status(home)
    preview = home.run("store", "facts", "migrate")
    still_before = _status(home)
    applied = home.run("store", "facts", "migrate", "--apply", "--json")
    migrated = _status(home)
    planned = home.run(
        "store", "facts", "refresh", "--head", MARQO_HEAD, "--asset", chosen, "--json"
    )
    after_plan = _status(home)
    refreshed = home.run(
        "store", "facts", "refresh", "--head", MARQO_HEAD, "--asset", chosen, "--apply"
    )
    after = _status(home)

    assert shown.returncode == 0, shown.explain()
    assert "Detector cache contract: detector-facts-v1" in shown.stdout
    assert f"{MARQO_HEAD}@{MARQO_STILL_EQUIVALENT}: {len(stills)} facts, migrate" in shown.stdout
    assert before[(MARQO_HEAD, MARQO_STILL_EQUIVALENT, "migrate")] == len(stills)
    # A preview changes nothing and names the pictures it would carry forward.
    assert preview.returncode == 0, preview.explain()
    assert f"{len(stills)} compatible facts" in preview.stdout
    assert "Preview only" in preview.stdout
    assert all(asset_id in preview.stdout for asset_id in stills)
    assert still_before == before
    # --apply copies them to the current version and keeps the old rows.
    assert applied.returncode == 0, applied.explain()
    assert json.loads(applied.stdout)["eligible"] == len(stills)
    assert migrated[(MARQO_HEAD, MARQO_VERSION, "reusable")] == len(stills)
    assert migrated[(MARQO_HEAD, MARQO_STILL_EQUIVALENT, "superseded")] == len(stills)
    # A refresh is planned first, then removes every version of only the named pair.
    assert planned.returncode == 0, planned.explain()
    assert json.loads(planned.stdout)["facts"] == 2
    assert after_plan == migrated
    assert refreshed.returncode == 0, refreshed.explain()
    assert "Selected facts removed" in refreshed.stdout
    assert after[(MARQO_HEAD, MARQO_VERSION, "reusable")] == len(kept)
    assert after[(MARQO_HEAD, MARQO_STILL_EQUIVALENT, "superseded")] == len(kept)
    assert after[("doc_docling", "det-v2", "reusable")] == 1
