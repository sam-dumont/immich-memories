"""A cut's pool: every picture it saw, what became of each, and the owner's word on it."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from immich_memories.analysis.editorial_source_snapshot import SNAPSHOT_NAME, source_payload
from tests.conftest import make_asset
from tests.web_api_fixtures import api_client, config_in, save_run, selection_trace

RUN = "20260927_100000_f00d"


def _cut_with_pool(tmp_path):
    config = config_in(tmp_path)
    attempt = save_run(config, RUN, trace=selection_trace())
    pool = [
        make_asset("woods-9", file_created_at=datetime(2024, 6, 15, tzinfo=UTC)),
        make_asset("garden-1", file_created_at=datetime(2024, 6, 8, tzinfo=UTC)),
        make_asset("lake-1", file_created_at=datetime(2024, 6, 21, tzinfo=UTC)),
    ]
    (attempt / SNAPSHOT_NAME).write_text(json.dumps(source_payload(pool), default=str))
    return config, api_client(config)


def test_the_pool_lists_what_the_cut_saw_in_capture_order_with_each_fate(tmp_path):
    _config, client = _cut_with_pool(tmp_path)

    pool = client.get(f"/api/v1/runs/{RUN}/pool").json()

    assert pool["total"] == 3
    assert [item["asset_id"] for item in pool["items"]] == ["garden-1", "woods-9", "lake-1"]
    garden, woods, _lake = pool["items"]
    assert garden["in_cut"] is True and woods["in_cut"] is False
    assert "a near duplicate of the path shot" in woods["fate"]
    assert woods["hold"] == {"decision": None, "reasons": [], "can_clear": False}


def test_never_use_is_the_owner_s_word_across_runs_and_undo_forgets_it(tmp_path):
    config, client = _cut_with_pool(tmp_path)

    decided = client.post("/api/v1/pictures/woods-9/decision", json={"action": "never_use"})
    pool = client.get(f"/api/v1/runs/{RUN}/pool").json()["items"]
    forgotten = client.post("/api/v1/pictures/woods-9/decision", json={"action": "forget"})

    assert decided.status_code == 200 and decided.json()["decision"] == "never_use"
    assert next(i for i in pool if i["asset_id"] == "woods-9")["hold"]["decision"] == "never_use"
    assert forgotten.json()["decision"] is None


def test_the_pool_opens_on_this_memory_s_own_pictures_and_counts_the_rest(tmp_path):
    config = config_in(tmp_path)
    trace = selection_trace()
    # The first pass saw it; the editor, given only this memory's material, never did.
    trace.editorial_passes[0] = trace.editorial_passes[0].__class__(
        **{
            **vars(trace.editorial_passes[0]),
            "input_ids": ("garden-1", "lake-1", "woods-9", "attic-2"),
        }
    )
    attempt = save_run(config, RUN, trace=trace)
    pool = [
        make_asset("garden-1", file_created_at=datetime(2024, 6, 8, tzinfo=UTC)),
        make_asset("attic-2", file_created_at=datetime(2024, 6, 9, tzinfo=UTC)),
    ]
    (attempt / SNAPSHOT_NAME).write_text(json.dumps(source_payload(pool), default=str))

    client = api_client(config)
    garden, attic = client.get(f"/api/v1/runs/{RUN}/pool").json()["items"]

    assert garden["reachable"] is True
    assert attic["reachable"] is False
    assert attic["fate"].startswith("Outside this memory")
    # The page opens on this memory's own pictures, and says how many it left aside.
    mine = client.get(f"/api/v1/runs/{RUN}/pool", params={"reachable_only": True}).json()
    assert [item["asset_id"] for item in mine["items"]] == ["garden-1"]
    assert (mine["total"], mine["outside"]) == (1, 1)


def test_the_pool_s_ticks_are_the_owner_s_last_pass_saved_as_a_revision_without_a_recut(tmp_path):
    _config, client = _cut_with_pool(tmp_path)

    saved = client.post(
        f"/api/v1/runs/{RUN}/revisions", json={"added": ["woods-9"], "removed": ["lake-1"]}
    )
    refused = client.post(f"/api/v1/runs/{RUN}/revisions", json={"added": ["a-stranger"]})

    assert saved.status_code == 201
    assert (saved.json()["added"], saved.json()["removed"]) == (["woods-9"], ["lake-1"])
    assert refused.status_code == 422 and "not in this cut's pool" in refused.json()["detail"]
    assert client.post(f"/api/v1/runs/{RUN}/recut", json={}).status_code in {404, 405}


def _spotlight_pool(tmp_path, *, people: list[str]):
    from immich_memories.api.models import Person

    config = config_in(tmp_path)
    attempt = save_run(config, RUN, trace=selection_trace())
    ada = Person(id="face-ada", name="Ada")
    face = make_asset("garden-1", file_created_at=datetime(2024, 6, 8, 9, tzinfo=UTC))
    face.people = [ada]
    feeding = make_asset("woods-9", file_created_at=datetime(2024, 6, 8, 9, 30, tzinfo=UTC))
    payload = source_payload([face, feeding]) | {"people": people, "person_match": "and"}
    (attempt / SNAPSHOT_NAME).write_text(json.dumps(payload, default=str))
    return api_client(config)


def test_a_picture_the_person_s_episode_brought_is_marked_so_the_owner_can_untick_it(tmp_path):
    """The face was found elsewhere in the episode, not on this picture (#1438)."""
    client = _spotlight_pool(tmp_path, people=["Ada"])

    items = client.get(f"/api/v1/runs/{RUN}/pool").json()["items"]

    assert {item["asset_id"]: item["same_episode"] for item in items} == {
        "garden-1": False,
        "woods-9": True,
    }


def test_a_memory_about_nobody_marks_nothing(tmp_path):
    client = _spotlight_pool(tmp_path, people=[])

    items = client.get(f"/api/v1/runs/{RUN}/pool").json()["items"]

    assert not any(item["same_episode"] for item in items)
