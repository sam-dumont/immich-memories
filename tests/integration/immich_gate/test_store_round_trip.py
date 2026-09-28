"""Real-Immich gate: what the product writes to its store comes back out of it.

Runs on whichever backend the Makefile gave the gate (`IMMICH_GATE_DATABASE`), so the
same assertions hold on SQLite and on PostgreSQL. Everything goes through the CLI a
user runs; the store is only read here, to check what those runs left in it.
"""

from __future__ import annotations

import re
from pathlib import Path

from immich_memories.db import Store
from immich_memories.db.inventory import table_digest
from immich_memories.db.tables.annotations import face_reads, head_facts, pixel_facts
from immich_memories.people.companion import load_document, people_entries
from immich_memories.store.owner_decisions import NEVER_USE, decisions
from immich_memories.tracking.run_database import RunDatabase
from tests.e2e.fake_library import CAST, LIBRARY, STORY_OF
from tests.integration.immich_fixtures import requires_immich
from tests.integration.immich_gate.conftest import FIXTURE_MONTH
from tests.integration.immich_gate.gate_cli import run_cli

pytestmark = [requires_immich]

# What preparation banks per picture on the NAS tier. Each row carries the time it
# was decided, so a producer that ran again would change its table's digest.
_FACT_TABLES = (head_facts, pixel_facts, face_reads)
_REPORT_ROW = re.compile(r"^(?P<producer>\S+)\s+(?P<pending>\d+)\s+\d+\.\d+\s")


def _ok(result) -> str:
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    return output


def _fact_digests(store: Store) -> dict[str, tuple[int, str]]:
    with store.connect() as connection:
        return {table.name: table_digest(connection, table) for table in _FACT_TABLES}


def _pending_by_producer(output: str) -> dict[str, int]:
    rows = (_REPORT_ROW.match(line.strip()) for line in output.splitlines())
    return {
        row["producer"]: int(row["pending"])
        for row in rows
        if row is not None and row["producer"] != "total"
    }


def test_a_people_scan_is_read_back_from_the_store(gate_store):
    _ok(run_cli("people", "scan", "--min-assets", "1"))

    names = {entry.get("name") for entry in people_entries(load_document(gate_store))}
    assert set(CAST) <= names
    shown = _ok(run_cli("people", "show"))
    assert all(name in shown for name in CAST)


def test_an_owner_decision_is_read_back_from_the_store(gate_client, gate_store):
    # A picture no story carries, so the decision cannot change another test's cut.
    spare = next(p for p in LIBRARY if not p.is_video and p.asset_id not in STORY_OF)
    stills = gate_client.get_photos_for_date_range(FIXTURE_MONTH)
    asset_id = next(a.id for a in stills if a.original_file_name == spare.filename)

    _ok(run_cli("pictures", "never-use", asset_id))
    assert decisions(gate_store, [asset_id]) == {asset_id: NEVER_USE}
    assert asset_id in _ok(run_cli("pictures", "list"))

    _ok(run_cli("pictures", "undo", asset_id))
    assert decisions(gate_store, [asset_id]) == {}


def test_a_second_preparation_reuses_the_banked_facts(gate_store):
    month = ("prepare", "--year", "2024", "--month", "6")
    _ok(run_cli(*month))
    banked = _fact_digests(gate_store)

    again = _ok(run_cli(*month))

    assert banked["head_facts"][0] > 0, banked
    assert banked["pixel_facts"][0] > 0, banked
    assert _fact_digests(gate_store) == banked
    # Previews are looked up in the thumbnail cache every time; nothing else may be pending.
    pending = _pending_by_producer(again)
    assert {producer for producer, count in pending.items() if count} <= {"previews"}, again


def test_a_rendered_film_is_recorded_in_the_run_history(gate_store, tmp_path):
    film = tmp_path / "june.mp4"
    _ok(
        run_cli(
            "generate",
            "--memory-type",
            "monthly_highlights",
            "--year",
            "2024",
            "--month",
            "6",
            "--include-photos",
            "--no-music",
            "--duration",
            "20",
            "--quiet",
            "--output",
            str(film),
        )
    )

    runs = RunDatabase(gate_store).list_runs(status="completed")
    # The film lands in a folder of its own beside the path asked for, named for the run.
    recorded = [run for run in runs if Path(run.output_path or "/").is_relative_to(tmp_path)]
    assert len(recorded) == 1, [run.output_path for run in runs]
    assert Path(recorded[0].output_path).stat().st_size > 0
    assert recorded[0].memory_type == "monthly_highlights"
    assert recorded[0].phase_events[-1]["phase"] == "complete"
    assert f"Run: {recorded[0].run_id}" in _ok(run_cli("runs", "show", recorded[0].run_id))
    assert {phase.phase_name for phase in recorded[0].phases} >= {"clip_extraction", "assembly"}
