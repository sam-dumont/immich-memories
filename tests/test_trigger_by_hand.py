"""A trigger call can say it was made by hand, and then it paces nothing.

`POST /api/trigger?force=true` is what `auto run --force` is on the command line: it skips
the cooldown and doesn't start one, so a film somebody asked for never holds back the
scheduled one. A call without the marker is the scheduled call it always was.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from immich_memories.automation.models import COOLDOWN_ACTIVE, AutoOutcome, AutoRunResult
from immich_memories.automation.runner import AutoRunner, StartedAutoRun
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.automation.status import is_within_cooldown
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.run_database import RunDatabase
from tests.auto_library_fake import (
    FakeGenerateChild,
    immich_serving,
    library_with_last_month,
    load_config_file,
)

TOKEN = "workflow-token"  # noqa: S105
_TOKEN_YAML = f"server:\n  trigger_token: {TOKEN}\nauth:\n  enabled: false\n"


@contextmanager
def _serving(config: Config) -> Iterator[None]:
    # WHY: replaces the on-disk config file the server reads on every request.
    with patch("immich_memories.web.trigger.get_config", return_value=config):
        yield


class _InlineWorker:
    """The background worker, run on the request's own thread so the test sees its end."""

    def __init__(self) -> None:
        self.results: list[AutoRunResult] = []

    def __call__(self, started: StartedAutoRun) -> None:
        from immich_memories.web.trigger import run_accepted

        self.results.append(run_accepted(started))


@pytest.fixture
def child(tmp_path: Path):
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records a finished film in the store.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


@pytest.fixture
def worker() -> _InlineWorker:
    return _InlineWorker()


@pytest.fixture
def client(worker: _InlineWorker) -> TestClient:
    from immich_memories.web.trigger import register_trigger_routes

    app = FastAPI()
    register_trigger_routes(app, submit=worker)
    return TestClient(app, raise_server_exceptions=False)


def _cooling(config: Config) -> bool:
    return is_within_cooldown(RunDatabase(open_store(config)), 24)


def _post(client: TestClient, config: Config, query: str = "", token: str = TOKEN):
    with _serving(config), immich_serving(library_with_last_month()):
        return client.post(f"/api/trigger{query}", headers={"x-api-key": token})


class TestAByHandCall:
    @pytest.mark.feature("automation.trigger-by-hand")
    def test_makes_its_film_and_starts_no_cooldown(
        self, tmp_path: Path, client: TestClient, worker: _InlineWorker, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, _TOKEN_YAML)

        response = _post(client, config, "?force=true")

        body = response.json()
        assert response.status_code == 202
        assert body["forced"] is True
        assert [result.outcome for result in worker.results] == [AutoOutcome.COMPLETED]
        attempt = AutomationStateStore(open_store(config)).get_attempt(body["attempt_id"])
        assert attempt is not None
        assert attempt.forced is True
        assert not _cooling(config)

    @pytest.mark.feature("automation.trigger-by-hand")
    def test_runs_while_the_cooldown_is_active(
        self, tmp_path: Path, client: TestClient, worker: _InlineWorker, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, _TOKEN_YAML)
        with immich_serving(library_with_last_month()):
            AutoRunner(config).run_one()
        assert _cooling(config)

        response = _post(client, config, "?force=true")

        assert response.status_code == 202
        assert len(worker.results) == 1
        # The month is already filmed, so nothing new is eligible; what matters is that the
        # cooldown is not what answered.
        assert worker.results[0].reason != COOLDOWN_ACTIVE

    @pytest.mark.feature("automation.trigger-by-hand")
    def test_still_needs_the_token(
        self, tmp_path: Path, client: TestClient, worker: _InlineWorker
    ) -> None:
        config = load_config_file(tmp_path, _TOKEN_YAML)

        response = _post(client, config, "?force=true", token="wrong-token")  # noqa: S106

        assert response.status_code == 401
        assert worker.results == []
        assert AutomationStateStore(open_store(config)).get_last_attempt() is None


class TestACallWithoutTheMarker:
    @pytest.mark.feature("automation.trigger-by-hand")
    @pytest.mark.parametrize("query", ["", "?force=false", "?force=maybe", "?force="])
    def test_is_the_scheduled_call_it_always_was(
        self,
        tmp_path: Path,
        client: TestClient,
        worker: _InlineWorker,
        child: FakeGenerateChild,
        query: str,
    ) -> None:
        config = load_config_file(tmp_path, _TOKEN_YAML)

        response = _post(client, config, query)

        body = response.json()
        assert response.status_code == 202
        assert body["forced"] is False
        attempt = AutomationStateStore(open_store(config)).get_attempt(body["attempt_id"])
        assert attempt is not None
        assert attempt.forced is False
        assert _cooling(config)

    @pytest.mark.feature("automation.trigger-by-hand")
    def test_is_still_held_back_by_the_cooldown(
        self, tmp_path: Path, client: TestClient, worker: _InlineWorker, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, _TOKEN_YAML)
        with immich_serving(library_with_last_month()):
            AutoRunner(config).run_one()

        _post(client, config)

        assert [result.reason for result in worker.results] == [COOLDOWN_ACTIVE]
