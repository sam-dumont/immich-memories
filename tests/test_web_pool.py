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
