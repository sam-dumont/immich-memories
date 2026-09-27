"""Suggestions in the browser are `auto suggest` and `auto run`, through the same runner."""

from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

from immich_memories.automation.runner import AutomationAlreadyRunningError
from immich_memories.web.suggestions import SUGGESTION_REASON, automation
from tests.web_api_fixtures import api_client, config_in


class _Runner:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy
        self.executed = threading.Event()
        self.kwargs: dict = {}
        self.last_variety_decision = SimpleNamespace(
            rejected=[
                SimpleNamespace(
                    candidate=SimpleNamespace(reason="May 2024"), rule="category_limit_two_of_six"
                )
            ]
        )
        self.last_backoff_skips = {"trip:2023": "failed twice"}
        self.last_suggest_status = SimpleNamespace(error=None)

    def suggest(self, limit):
        return [
            SimpleNamespace(
                memory_key="monthly_highlights:2024-06",
                memory_type="monthly_highlights",
                category=SimpleNamespace(value="monthly_review"),
                reason="June 2024",
                person_names=[],
                date_range_start=date(2024, 6, 1),
                date_range_end=date(2024, 6, 30),
                asset_count=133,
            )
        ]

    def start_one(self, reason):
        if self.busy:
            raise AutomationAlreadyRunningError("busy")
        assert reason == SUGGESTION_REASON

        def execute(**kwargs):
            self.kwargs = kwargs
            self.executed.set()

        return SimpleNamespace(attempt=SimpleNamespace(id="attempt-1"), execute=execute)


def _client(tmp_path, runner):
    client = api_client(config_in(tmp_path))
    # WHY: the runner reaches Immich and starts the CLI child; here only its answers matter.
    client.app.dependency_overrides[automation] = lambda: runner
    return client


def test_suggestions_list_candidates_and_why_others_were_set_aside(tmp_path):
    body = _client(tmp_path, _Runner()).get("/api/v1/suggestions").json()

    assert body["candidates"][0]["memory_key"] == "monthly_highlights:2024-06"
    assert body["candidates"][0]["asset_count"] == 133
    assert {"label": "May 2024", "rule": "category_limit_two_of_six"} in body["skipped"]
    assert {"label": "trip:2023", "rule": "failed twice"} in body["skipped"]


def test_running_a_suggestion_executes_it_like_auto_run_and_refuses_a_second(tmp_path):
    runner = _Runner()
    started = _client(tmp_path, runner).post(
        "/api/v1/suggestions/run",
        json={"memory_key": "monthly_highlights:2024-06", "dry_run": True},
    )

    assert started.status_code == 202 and started.json()["id"] == "attempt-1"
    assert runner.executed.wait(5)
    assert runner.kwargs == {"candidate_key": "monthly_highlights:2024-06", "dry_run": True}
    busy = _client(tmp_path, _Runner(busy=True)).post(
        "/api/v1/suggestions/run", json={"memory_key": "x"}
    )
    assert busy.status_code == 409
