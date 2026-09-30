"""Detector maintenance keeps compatible facts and makes selected refreshes explicit."""

import json

import click
from click.testing import CliRunner

from immich_memories.cache.embedding_cache import HeadFactStore
from immich_memories.cli.store_cmd import register_store_commands
from immich_memories.config_loader import Config
from immich_memories.triage.heads import HeadFact


def invoke(store, *args):
    @click.group()
    def root():
        pass

    register_store_commands(root)
    return CliRunner().invoke(
        root,
        ["store", "facts", *args],
        env={
            "IMMICH_MEMORIES_DATABASE_URL": store.location.url,
            "IMMICH_MEMORIES_DATABASE_SCHEMA": store.location.schema or "",
        },
        obj={
            "config": Config(
                database={"url": store.location.url, "schema_name": store.location.schema}
            )
        },
    )


def test_status_preserves_old_and_current_facts_and_names_refreshes(store):
    bank = HeadFactStore(store)
    bank.remember_facts(
        {"photo": [HeadFact("doc_docling", "photograph", 0.9, "det-v2")]},
        encoder_key="docling-project/DocumentFigureClassifier-v2.0",
    )
    bank.remember_facts(
        {"older": [HeadFact("doc_docling", "photograph", 0.8, "det-v1")]}, encoder_key="old"
    )
    assert "doc_docling@det-v2" in invoke(store, "status").output
    result = invoke(store, "status", "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["contract"] == "detector-facts-v1"
    assert report["rows"] == [
        {"head": "doc_docling", "version": "det-v1", "facts": 1, "state": "refresh"},
        {"head": "doc_docling", "version": "det-v2", "facts": 1, "state": "reusable"},
    ]
    assert (
        bank.facts_for(["older"], head="doc_docling", version="det-v1")["older"].confidence == 0.8
    )
    assert (
        bank.facts_for(["photo"], head="doc_docling", version="det-v2")["photo"].confidence == 0.9
    )


def test_migration_is_previewed_then_carries_only_verified_stills(store):
    from immich_memories.analysis.editorial_preparation_detectors import MARQO_ONNX_ID
    from immich_memories.store.editorial_preparation import remember_assets
    from tests.test_editorial_preparation import asset

    remember_assets(
        store,
        [
            asset("photo"),
            asset("already"),
            asset("wrong"),
            asset("video").model_copy(update={"type": "VIDEO"}),
        ],
    )
    bank = HeadFactStore(store)
    bank.remember_facts(
        {
            key: [HeadFact("nsfw_marqo", "no", 0.2, "det-v2")]
            for key in ["photo", "already", "video", "unknown"]
        },
        encoder_key=MARQO_ONNX_ID,
    )
    bank.remember_facts(
        {"wrong": [HeadFact("nsfw_marqo", "no", 0.2, "det-v2")]}, encoder_key="other-model"
    )
    bank.remember_facts(
        {"already": [HeadFact("nsfw_marqo", "yes", 0.9, "det-v3")]}, encoder_key=MARQO_ONNX_ID
    )
    assert "Preview only" in invoke(store, "migrate").output
    result = invoke(store, "migrate", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["eligible"] == 1
    assert not bank.facts_for(["photo"], head="nsfw_marqo", version="det-v3")
    result = invoke(store, "migrate", "--apply", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["asset_ids"] == ["photo"]
    current = bank.facts_for(
        ["photo", "already", "video", "unknown", "wrong"], head="nsfw_marqo", version="det-v3"
    )
    assert set(current) == {"photo", "already"}
    assert current["photo"].confidence == 0.2
    assert current["already"].confidence == 0.9
    assert bank.facts_for(["photo"], head="nsfw_marqo", version="det-v2")
    again = invoke(store, "migrate", "--apply", "--json")
    assert json.loads(again.output)["eligible"] == 0
    assert "Applied; old facts retained" in invoke(store, "migrate", "--apply").output


def test_refresh_is_explicit_and_limited_to_selected_assets_and_heads(store):
    bank = HeadFactStore(store)
    for version in ["det-v2", "det-v3"]:
        bank.remember_facts(
            {key: [HeadFact("nsfw_marqo", "no", 0.2, version)] for key in ["chosen", "keep"]},
            encoder_key="marqo",
        )
    bank.remember_facts(
        {"chosen": [HeadFact("doc_docling", "photograph", 0.9, "det-v2")]}, encoder_key="docling"
    )
    assert (
        "Preview only"
        in invoke(store, "refresh", "--head", "nsfw_marqo", "--asset", "chosen").output
    )
    result = invoke(store, "refresh", "--head", "nsfw_marqo", "--asset", "chosen", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["facts"] == 2
    assert bank.facts_for(["chosen"], head="nsfw_marqo", version="det-v3")
    result = invoke(
        store, "refresh", "--head", "nsfw_marqo", "--asset", "chosen", "--apply", "--json"
    )
    assert result.exit_code == 0, result.output
    for version in ["det-v2", "det-v3"]:
        assert set(bank.facts_for(["chosen", "keep"], head="nsfw_marqo", version=version)) == {
            "keep"
        }
    assert bank.facts_for(["chosen"], head="doc_docling", version="det-v2")
    assert invoke(store, "refresh", "--head", "nsfw_marqo", "--apply").exit_code == 2
    assert invoke(store, "refresh", "--asset", "keep", "--apply").exit_code == 2


def test_status_distinguishes_superseded_unrecognized_and_malformed_answers(store):
    bank = HeadFactStore(store)
    bank.remember_facts(
        {
            "p": [
                HeadFact("doc_docling", "photograph", 0.9, "det-v1"),
                HeadFact("doc_docling", "photograph", 0.9, "det-v2"),
            ],
            "bad": [HeadFact("doc_docling", "", 0.9, "det-v2")],
            "custom": [HeadFact("personal", "example", 0.9, "v1")],
        },
        encoder_key="fixture",
    )
    result = invoke(store, "status", "--json")
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)["rows"]
    assert {(row["head"], row["version"], row["state"]) for row in rows} == {
        ("doc_docling", "det-v1", "superseded"),
        ("doc_docling", "det-v2", "reusable"),
        ("doc_docling", "det-v2", "refresh"),
        ("personal", "v1", "unrecognized"),
    }
