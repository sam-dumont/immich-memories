"""The owner's decisions on a picture live in the store, on either backend."""

from __future__ import annotations

import json

from immich_memories.store import owner_decisions
from tests.annotation_rows import add_rows, read_rows


def test_a_decision_covers_the_live_photo_clip_the_store_knows(store):
    add_rows(store, "annotation_assets", {"asset_id": "still", "live_photo_video_id": "clip"})

    written = owner_decisions.decide(store, "still", owner_decisions.NEVER_USE, via="cli")

    assert written == ("still", "clip")
    assert owner_decisions.decisions(store) == {"clip": "never_auto", "still": "never_auto"}


def test_a_new_decision_replaces_the_old_one_and_leaves_producer_flags_alone(store):
    add_rows(
        store,
        "asset_flags",
        {"asset_id": "a", "flag": "never_auto", "source": "a-detector", "evidence": "{}"},
    )
    owner_decisions.decide(store, "a", owner_decisions.NEVER_USE, via="web", clip_id="a")

    owner_decisions.decide(store, "a", owner_decisions.clearance_for("family"), via="cli")

    rows = {(row["flag"], row["source"]) for row in read_rows(store, "asset_flags")}
    assert rows == {("never_auto", "a-detector"), ("cleared_family", "owner")}
    assert owner_decisions.decisions(store, ["a", "b"]) == {"a": "cleared_family"}


def test_the_record_says_which_surface_decided(store):
    owner_decisions.decide(store, "a", owner_decisions.CLEAR_HOLD, via="web")

    [row] = read_rows(store, "asset_flags")
    assert json.loads(row["evidence"])["via"] == "web"
    assert row["written_at"] is not None


def test_forgetting_drops_only_the_owners_word(store):
    add_rows(store, "annotation_assets", {"asset_id": "still", "live_photo_video_id": "clip"})
    add_rows(store, "asset_flags", {"asset_id": "still", "flag": "nsfw", "source": "a-detector"})
    owner_decisions.decide(store, "still", owner_decisions.NEVER_USE, via="cli")

    assert owner_decisions.forget(store, "still") == ("still", "clip")

    assert owner_decisions.decisions(store) == {}
    assert [row["source"] for row in read_rows(store, "asset_flags")] == ["a-detector"]


def test_live_clips_reads_a_lifetime_of_pictures_in_bounded_batches(store):
    add_rows(
        store,
        "annotation_assets",
        *({"asset_id": f"still-{n}", "live_photo_video_id": f"clip-{n}"} for n in range(2000)),
    )

    clips = owner_decisions.live_clips(store, [f"still-{n}" for n in range(2000)] + ["unknown"])

    assert len(clips) == 2000
    assert clips["still-1999"] == "clip-1999"
