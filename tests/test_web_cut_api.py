"""The review workspace reads one cut: the order it plays, and every recorded reason for each shot."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config
from tests.web_api_fixtures import api_client, config_in, save_run, selection_trace

RUN = "20260913_080000_ab12"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return config_in(tmp_path)


@pytest.fixture
def client(config: Config) -> TestClient:
    return api_client(config)


def test_a_rules_only_cut_plays_in_capture_order_with_the_path_each_shot_took(client, config):
    save_run(config, RUN, trace=selection_trace())

    cut = client.get(f"/api/v1/runs/{RUN}/cut").json()

    assert cut["thesis"] == "A month that ends by the lake."
    assert cut["model_polish"] is False
    garden, lake = cut["shots"]
    assert (garden["asset_id"], garden["position"], garden["start"]) == ("garden-1", 1, 0.0)
    assert garden["reason"] == "the table still out"
    assert garden["story_title"] == "Lunch in the garden"
    # The same reading `runs why` prints: "kept at the picture review".
    assert garden["selection"]["kept_at"] == "the picture review"
    assert garden["selection"]["left_out_at"] is None
    assert garden["model"] is None
    assert lake["motion"] is True
    assert lake["source_interval"] == [12.5, 16.5]
    assert garden["source_interval"] is None


def test_a_polished_cut_carries_the_model_record_on_the_shot_it_explains(client, config):
    save_run(
        config,
        RUN,
        polish={
            "ran": True,
            "verdicts": {"old-lake": {"state": "weak", "named_by": 1, "why": "A repeated view"}},
            "slots": [
                {
                    "rule": "vote-weak",
                    "replacing": "old-lake",
                    "chosen": "lake-1",
                    "outcome": "seated",
                }
            ],
            "revoked_by_the_fit_check": [],
        },
    )

    cut = client.get(f"/api/v1/runs/{RUN}/cut").json()

    assert cut["model_polish"] is True
    lake = next(shot for shot in cut["shots"] if shot["asset_id"] == "lake-1")
    assert lake["model"]["replaced_asset_id"] == "old-lake"
    assert lake["model"]["model_reason"] == "A repeated view"
    assert lake["selection"] is None


def test_a_run_without_a_saved_cut_is_a_404(client, config):
    save_run(config, RUN, cut=False)

    assert client.get(f"/api/v1/runs/{RUN}/cut").status_code == 404
    assert client.get("/api/v1/runs/never-ran/cut").status_code == 404


def test_a_run_reads_its_record_and_hands_out_the_retained_child_output(client, config):
    from uuid import uuid4

    from immich_memories.operations.auto_output import output_log_path

    attempt_id = str(uuid4())
    save_run(
        config,
        RUN,
        cut=False,
        status="failed",
        source="auto",
        automation_attempt_id=attempt_id,
        warnings=["The provider stopped answering"],
    )
    log = output_log_path(config.cache.cache_path, attempt_id)
    log.parent.mkdir(parents=True)
    log.write_text("stdout:\nSelected 12 clips\n")

    run = client.get(f"/api/v1/runs/{RUN}").json()
    child = client.get(f"/api/v1/runs/{RUN}/child-output")

    assert (run["status"], run["source"], run["has_cut"]) == ("failed", "auto", False)
    assert run["warnings"] == ["The provider stopped answering"]
    assert run["delivery_status"] == "not_requested"
    assert run["child_output"] is True
    assert child.status_code == 200 and "Selected 12 clips" in child.text
    assert client.get("/api/v1/runs/nobody").status_code == 404


def test_a_hand_typed_attempt_id_has_no_child_output_instead_of_failing(client, config):
    save_run(config, RUN, cut=False, source="auto", automation_attempt_id="last-nights-run")

    assert client.get(f"/api/v1/runs/{RUN}").json()["child_output"] is False
    assert client.get(f"/api/v1/runs/{RUN}/child-output").status_code == 404


def test_a_shot_offers_the_rest_of_its_moment_with_what_became_of_each(client, config):
    save_run(config, RUN, trace=selection_trace())

    garden = client.get(f"/api/v1/runs/{RUN}/cut").json()["shots"][0]

    woods, other = garden["alternatives"]
    assert woods["asset_id"] == "woods-9"
    assert woods["facts"] == "photo, 2024-06-15"
    assert "a near duplicate of the path shot" in woods["fate"]
    assert other["asset_id"] == "garden-3"
    assert other["fate"] == "Not in this cut's pool"


def test_edits_save_as_revisions_and_a_refused_one_says_why(client, config):
    save_run(config, RUN)

    saved = client.post(f"/api/v1/runs/{RUN}/revisions", json={"removed": ["garden-1"]})
    refused = client.post(
        f"/api/v1/runs/{RUN}/revisions", json={"swaps": {"garden-1": "somebody-else"}}
    )
    history = client.get(f"/api/v1/runs/{RUN}/revisions").json()

    assert saved.status_code == 201
    assert saved.json()["number"] == 1 and saved.json()["removed"] == ["garden-1"]
    assert refused.status_code == 422
    assert "not another picture of that moment" in refused.json()["detail"]
    assert [revision["number"] for revision in history] == [1]


def test_the_story_view_orders_stories_by_weight_and_lists_what_carries_each(client, config):
    import json

    from tests.web_api_fixtures import PLAN

    attempt = save_run(config, RUN)
    plan = json.loads(json.dumps(PLAN))
    plan["story"]["episodes"][0].update(weight="minor", purpose="the everyday", granted=2)
    plan["story"]["episodes"][1].update(weight="dominant", purpose="the trip")
    (attempt / "plan.private.json").write_text(json.dumps(plan))
    (attempt / "preparation.private.json").write_text(json.dumps({"tier": "no_captions"}))

    story = client.get(f"/api/v1/runs/{RUN}/story").json()

    assert story["thesis"] == "A month that ends by the lake."
    assert "classified, not read" in story["preparation"]
    lake, garden = story["stories"]
    assert (lake["title"], lake["weight"], lake["granted"]) == (
        "Two nights by the lake",
        "dominant",
        1,
    )
    assert [c["asset_id"] for c in lake["carriers"]] == ["lake-1"]
    assert lake["carriers"][0]["motion"] is True
    assert garden["carriers"][0]["reason"] == "the table still out"
    assert (garden["weight"], garden["granted"]) == ("minor", 2)


def test_a_run_without_a_plan_has_no_story(client, config):
    save_run(config, RUN, cut=False)

    assert client.get(f"/api/v1/runs/{RUN}/story").status_code == 404
