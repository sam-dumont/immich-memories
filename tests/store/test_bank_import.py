"""The JSON banks come into the store once, whole, and are left exactly as they were."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from immich_memories.analysis import editorial_shareability as share
from immich_memories.analysis.editorial_structure_audience import AudienceBank
from immich_memories.db.tables import owner_edits
from immich_memories.store.legacy_banks import import_legacy
from immich_memories.store.vote_banks import VoteBank

HOLD = {"verdict": "do_not_show", "finding": "exposure_evidence", "policy": "nsfw-head"}
TEXT = {
    "verdict": "family_only",
    "finding": "private_activity",
    "policy": "old-prompt",
    "text_version": f"{share.AUDIENCE_PROMPT_VERSION}|{share.AUDIENCE_CHECK_POLICY_VERSION}",
}
EDIT = {
    "version": "editorial-owner-edits-v1",
    "original_timing_sha256": "a" * 64,
    "result_timing_sha256": "b" * 64,
    "removed_asset_ids": ["asset-3"],
    "interval_edits": [],
    "timing_policy_changed": True,
    "original_policy": {"target_seconds": 60.0},
    "requested_policy": {"target_seconds": 45.0},
    "artifact_name": "summer.owner-edits-1234abcd.private.json",
}


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    """Where the legacy home and its films sit; the environment names the output directory,
    as the suite's does, and it beats config.yaml as it does at run time."""
    root = tmp_path / "legacy"
    monkeypatch.setenv("IMMICH_MEMORIES_CACHE__DIRECTORY", str(root / ".immich-memories" / "cache"))
    monkeypatch.setenv("IMMICH_MEMORIES_OUTPUT__DIRECTORY", str(root / "Films"))
    return root


def _legacy_home(root: Path) -> Path:
    """A home with banks in both places the code keeps them, and one reviewed film."""
    home = root / ".immich-memories"
    elsewhere = root / "annotations-elsewhere"
    _write(
        home / "config.yaml",
        {
            "output": {"directory": "~/Somewhere-else"},
            "advanced": {
                "editorial": {"annotation_database": str(elsewhere / "annotations.sqlite")}
            },
        },
    )
    _write(
        home / "cache" / "structure-banks" / "audience-verdicts.private.json",
        {
            "answers": {"full|laya": {"key-1": {"parsed": True, "verdict": "share"}}},
            "holds": {"asset-1": {"permanent": HOLD, "text": TEXT}},
        },
    )
    _write(
        elsewhere / "structure-banks" / "audience-verdicts.private.json",
        {"answers": {"full|rules": {"key-2": {"parsed": True, "verdict": "family_only"}}}},
    )
    _write(
        elsewhere / "structure-banks" / "month-2024-02" / "memory-worthy.private.json",
        {
            "c" * 64: {"source": {"P01": "a birthday"}, "source_envelope": {"shape": "wrapped"}},
            "rows": {"d" * 64: {"votes": 2, "why": "a birthday"}},
            "rows-one-order": {"e" * 64: {"votes": 1, "why": ""}},
        },
    )
    _write(
        home / "cache" / "structure-banks" / "trip-x" / "thesis-fit.private.json",
        {"f" * 64: {"source": {}, "hashed": {}}},
    )
    _write(root / "Films" / "2024" / "summer.owner-edits-1234abcd.private.json", EDIT)
    return home


def _fingerprints(root: Path) -> dict[Path, tuple[str, int]]:
    return {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_every_bank_entry_arrives_once_and_the_files_stay_as_they_were(store, root):
    home = _legacy_home(root)
    before = _fingerprints(root)

    first = import_legacy(store, home)
    second = import_legacy(store, home)

    assert first.imported == 9
    assert (second.imported, second.skipped) == (0, 9)
    assert _fingerprints(root) == before
    assert AudienceBank(store, answerer="full|laya").answer("key-1") == {
        "parsed": True,
        "verdict": "share",
    }
    assert AudienceBank(store, answerer="full|rules").answer("key-2")["verdict"] == "family_only"
    assert AudienceBank(store, answerer="x").held("asset-1") == HOLD
    worthy = VoteBank(store, "memory-worthy", "month-2024-02")
    assert worthy["rows"] == {"d" * 64: {"votes": 2, "why": "a birthday"}}
    assert worthy["rows-one-order"] == {"e" * 64: {"votes": 1, "why": ""}}
    assert worthy["c" * 64]["source_envelope"] == {"shape": "wrapped"}
    assert set(VoteBank(store, "thesis-fit", "trip-x")) == {"f" * 64}
    with store.connect() as connection:
        edit = connection.execute(sa.select(owner_edits)).one()
    assert (edit.edit_id, edit.film_stem, edit.record) == ("1234abcd", "summer", EDIT)


def test_the_store_keeps_its_own_answer_but_a_stricter_legacy_hold_tightens(store, root):
    home = _legacy_home(root)
    AudienceBank(store, answerer="full|laya").keep("key-1", {"parsed": True, "verdict": "no"})
    banked = AudienceBank(store, answerer="r")
    banked.hold("asset-1", {**HOLD, "verdict": "family_only"})
    banked.flush()

    outcome = import_legacy(store, home)

    assert AudienceBank(store, answerer="full|laya").answer("key-1") == {
        "parsed": True,
        "verdict": "no",
    }
    assert AudienceBank(store, answerer="r").held("asset-1") == HOLD
    assert any("tightened" in note for note in outcome.notes)


def test_a_home_without_banks_imports_nothing(store, root):
    outcome = import_legacy(store, root / ".immich-memories")

    assert (outcome.imported, outcome.skipped) == (0, 0)
