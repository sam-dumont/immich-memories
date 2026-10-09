"""`annotations.sqlite` and `judgments.db` come into the store once, keys and owner rows intact."""

from __future__ import annotations

import hashlib
from datetime import datetime

from immich_memories.store import owner_decisions
from immich_memories.store.episode_readings import EpisodeReadingIdentity, EpisodeReadingStore
from immich_memories.store.legacy_annotations import import_legacy
from tests.annotation_rows import add_rows, count_rows, read_rows

from .legacy_annotation_files import write_annotations, write_judgments


def _fingerprint(path) -> tuple[str, float]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime


def test_every_legacy_row_arrives_under_its_own_key(store, tmp_path):
    home = tmp_path / "home"
    write_annotations(home / "cache" / "annotations.sqlite")
    write_judgments(home / "cache" / "judgments.db")

    outcome = import_legacy(store, home)

    assert outcome.imported > 0
    assert owner_decisions.decisions(store) == {"still-1": "cleared_family"}
    [reading] = read_rows(store, "editorial_episode_readings")
    assert (reading["group_id"], reading["producer_key"], reading["evidence_key"]) == (
        "group-1",
        "producer-1",
        "evidence-1",
    )
    assert reading["notable_moments"] == "[]"
    # A reading banked before readings named notable moments reads back with none.
    identity = EpisodeReadingIdentity("group-1", "producer-1", "evidence-1")
    assert EpisodeReadingStore(store).readings_for([identity])["group-1"].notable_moments == ()
    [head] = read_rows(store, "head_facts")
    assert (head["asset_id"], head["head"], head["version"], head["label"]) == (
        "still-1",
        "nsfw_marqo",
        "det-v3",
        "no",
    )
    assert head["decided_at"] == datetime(2026, 3, 1, 9, 30)
    assert {row["key"] for row in read_rows(store, "judgments")} == {"question-a", "question-b"}
    assert count_rows(store, "text_completion_failures") == 1
    [pixel] = read_rows(store, "pixel_facts")
    assert pixel["needs_rotation"] is False
    boxes = read_rows(store, "face_boxes")
    assert [(box["ordinal"], box["named"]) for box in boxes] == [(0, True), (1, False)]
    assert read_rows(store, "annotation_assets")[1]["favourite"] is True


def test_a_second_import_takes_nothing(store, tmp_path):
    home = tmp_path / "home"
    write_annotations(home / "cache" / "annotations.sqlite")
    write_judgments(home / "cache" / "judgments.db")
    import_legacy(store, home)

    again = import_legacy(store, home)

    assert again.imported == 0
    assert again.skipped > 0


def test_the_legacy_files_are_never_written(store, tmp_path):
    home = tmp_path / "home"
    annotations = write_annotations(home / "cache" / "annotations.sqlite")
    judgments = write_judgments(home / "cache" / "judgments.db")
    before = (_fingerprint(annotations), _fingerprint(judgments))

    import_legacy(store, home)

    assert (_fingerprint(annotations), _fingerprint(judgments)) == before


def test_a_store_answer_is_never_replaced_by_an_older_legacy_one(store, tmp_path):
    home = tmp_path / "home"
    write_annotations(home / "cache" / "annotations.sqlite")
    owner_decisions.decide(
        store, "still-1", owner_decisions.NEVER_USE, via="web", clip_id="still-1"
    )
    add_rows(store, "judgments", {"key": "question-a", "answer": "the newer answer"})
    add_rows(
        store,
        "face_boxes",
        {"asset_id": "still-1", "named": True, "x1": 0, "y1": 0, "x2": 1, "y2": 1},
    )

    import_legacy(store, home)

    # The owner's newer word stands, and the file's older one does not come back beside it.
    owner_rows = [row for row in read_rows(store, "asset_flags") if row["source"] == "owner"]
    assert [row["flag"] for row in owner_rows] == ["never_auto"]
    assert read_rows(store, "judgments")[0]["answer"] == "the newer answer"
    assert count_rows(store, "face_boxes") == 1


def test_a_relocated_annotation_file_named_in_the_config_is_imported(store, tmp_path):
    home = tmp_path / "home"
    elsewhere = write_annotations(tmp_path / "profile" / "bank.sqlite")
    home.mkdir()
    (home / "config.yaml").write_text(
        f"advanced:\n  editorial:\n    annotation_database: {elsewhere}\n"
    )

    outcome = import_legacy(store, home)

    assert str(elsewhere) in outcome.source
    assert owner_decisions.decisions(store) == {"still-1": "cleared_family"}


def test_a_cache_the_environment_moved_is_imported_without_a_config_file(
    store, tmp_path, monkeypatch
):
    # A container configures the app by environment alone and ships no config.yaml.
    home = tmp_path / "home"
    home.mkdir()
    write_annotations(tmp_path / "volume-cache" / "annotations.sqlite")
    monkeypatch.setenv("IMMICH_MEMORIES_CACHE__DIRECTORY", str(tmp_path / "volume-cache"))

    import_legacy(store, home)

    assert owner_decisions.decisions(store) == {"still-1": "cleared_family"}


def test_nothing_to_import_says_so(store, tmp_path):
    outcome = import_legacy(store, tmp_path)

    assert (outcome.imported, outcome.skipped) == (0, 0)
    assert outcome.notes


def test_legacy_discovery_keeps_relocated_paths_without_probing_runtime_hardware(
    tmp_path, monkeypatch, caplog
):
    from unittest.mock import patch

    from immich_memories.store.legacy_annotations import legacy_sources

    home = tmp_path / "legacy"
    home.mkdir()
    annotations = write_annotations(tmp_path / "moved" / "annotations.sqlite")
    monkeypatch.setenv("IMMICH_MEMORIES_CACHE__DIRECTORY", str(annotations.parent))
    monkeypatch.setenv("IMMICH_MEMORIES_TIER", "auto")
    # WHY: hardware detection is a machine boundary unrelated to locating legacy files.
    with patch(
        "immich_memories.config_tiers.inference_acceleration",
        side_effect=AssertionError("legacy discovery must not probe the runtime GPU"),
    ) as probe:
        found = legacy_sources(home)

    assert annotations in found
    assert not probe.called
    assert not caplog.records


def test_unreadable_legacy_config_warns_without_echoing_its_contents(tmp_path, caplog):
    from immich_memories.store.legacy_annotations import legacy_sources

    (tmp_path / "config.yaml").write_text("immich: {api_key: synthetic-private-corpus, broken: [\n")
    assert legacy_sources(tmp_path) == []
    assert "config.yaml unreadable for the import" in caplog.text
    assert "synthetic-private-corpus" not in caplog.text
