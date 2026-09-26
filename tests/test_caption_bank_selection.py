"""Reuse complete caption pairs and attribute them to the producer actually read."""

import sqlite3

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
)
from immich_memories.analysis.prepared_captions import prepared_captions
from immich_memories.config_loader import Config
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.store.caption_provenance import CaptionOrigin, origins_for, remember_origin
from immich_memories.store.editorial_preparation import initialize, missing_facts

LLM_MODEL = "llm-caption-v1@fixture"


def _bank(connection, asset, model, text, setting):
    source = DESCRIPTION_SOURCE if model == DESCRIPTION_MODEL else "llm-envelope-v3-compact"
    connection.execute(
        "INSERT INTO descriptions VALUES (?,?,?,?,?)", (asset, model, text, source, "now")
    )
    if setting is not None:
        connection.execute(
            "INSERT INTO description_fields VALUES (?,?,?,?,?)",
            (asset, model, "setting", setting, "now"),
        )


def test_reading_and_preparation_agree_on_one_complete_caption_pair(tmp_path):
    database = tmp_path / "annotations.sqlite"
    ids = ("both", "smol-only", "llm-only", "partial-smol")
    with sqlite3.connect(database) as connection:
        initialize(connection)
        for asset, model, text, setting in [
            ("both", DESCRIPTION_MODEL, "A dog runs.", "a park"),
            ("both", LLM_MODEL, "A different account.", "a room"),
            ("smol-only", DESCRIPTION_MODEL, "A boat sails.", "a lake"),
            ("llm-only", LLM_MODEL, "A cat sleeps.", "a room"),
            ("partial-smol", DESCRIPTION_MODEL, "An incomplete account.", None),
            ("partial-smol", LLM_MODEL, "A child runs.", "a garden"),
        ]:
            _bank(connection, asset, model, text, setting)
        missing, _ = missing_facts(
            connection,
            ids,
            description_model=LLM_MODEL,
            head_versions={},
            pixel_producer_key="fixture",
            preview_for=lambda _: b"",
        )
        assert not any(key.startswith("description:") for key in missing)

    repository = AssetAnnotationFactRepository(
        database, description_model=LLM_MODEL, head_versions={}, pixel_producer_key="fixture"
    )
    facts = repository.facts_for(ids).as_mapping()
    assert {asset: (facts[asset].description, facts[asset].setting) for asset in ids} == {
        "both": ("A dog runs.", "a park"),
        "smol-only": ("A boat sails.", "a lake"),
        "llm-only": ("A cat sleeps.", "a room"),
        "partial-smol": ("A child runs.", "a garden"),
    }
    config = Config(
        tier="nas", editorial={"annotation_database": str(database), "description_model": LLM_MODEL}
    )
    assert prepared_captions(config, ids)["both"] == "A dog runs."


def test_provenance_follows_the_complete_caption_that_was_reused():
    with sqlite3.connect(":memory:") as connection:
        initialize(connection)
        for asset, model, producer in [
            ("old", DESCRIPTION_MODEL, "original-smolvlm"),
            ("old", LLM_MODEL, "unused-llm"),
            ("new", LLM_MODEL, "new-llm"),
        ]:
            _bank(connection, asset, model, "A cat sleeps.", "a room")
            remember_origin(
                connection,
                asset,
                model,
                CaptionOrigin(model_id=producer, endpoint="http://localhost:43210/v1"),
            )

        grouped = origins_for(connection, ("old", "new"), LLM_MODEL)

    assert {origin["model_id"] for origin in grouped["origins"]} == {"original-smolvlm", "new-llm"}
    assert sum(origin["assets"] for origin in grouped["origins"]) == 2
