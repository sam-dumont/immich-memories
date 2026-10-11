"""Automation started by the web server renders with the config it was started with (#2363)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from immich_memories.automation.models import AutoOutcome
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config, load_config
from immich_memories.db import open_store
from tests.auto_library_fake import FakeGenerateChild, immich_serving, library_with_last_month

TOKEN = "workflow-token"  # noqa: S105


@pytest.fixture
def alt_config(tmp_path: Path) -> tuple[Path, Config]:
    """`immich-memories --config alt.yaml ui`: a second setup with its own store."""
    path = tmp_path / "alt" / "alt.yaml"
    path.parent.mkdir()
    path.write_text(
        "immich:\n  url: https://immich.example.test\n  api_key: alt-key\n"
        f"cache:\n  database: {tmp_path / 'alt' / 'runs.db'}\n"
        f"  directory: {tmp_path / 'alt' / 'cache'}\n"
        f"server:\n  trigger_token: {TOKEN}\n"
        "advanced:\n  automation:\n    enabled: true\n    daily_at: '09:00'\n"
        "    detect_trips: false\n"
    )
    return path, load_config(path)


@pytest.fixture
def child(tmp_path: Path):
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in writes to the store its argv names.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


def _config_of(child: FakeGenerateChild) -> str | None:
    """The file the first child was told to load, if any."""
    cmd = child.commands[0]
    return cmd[cmd.index("--config") + 1] if "--config" in cmd else None


def _attempt(config: Config, attempt_id: str):
    return AutomationStateStore(open_store(config)).get_attempt(attempt_id)


@pytest.mark.feature("automation.web-honours-config")
def test_a_trigger_runs_its_child_with_the_servers_config(alt_config, child) -> None:
    from immich_memories.web.trigger import register_trigger_routes

    path, config = alt_config
    app = FastAPI()
    register_trigger_routes(app, submit=lambda started: started.execute())
    with immich_serving(library_with_last_month()):
        response = TestClient(app).post("/api/trigger", headers={"x-api-key": TOKEN})

    assert response.status_code == 202
    assert _config_of(child) == str(path)
    attempt = _attempt(config, response.json()["attempt_id"])
    assert attempt is not None and attempt.outcome is AutoOutcome.COMPLETED, attempt


@pytest.mark.feature("automation.web-honours-config")
def test_the_daily_timer_runs_its_child_with_the_servers_config(alt_config, child) -> None:
    from immich_memories.automation.in_process_scheduler import InProcessScheduler

    path, config = alt_config
    at_ten = datetime.now().astimezone().replace(hour=10, minute=0)
    timer = InProcessScheduler(lambda: config, clock=lambda: at_ten)
    with immich_serving(library_with_last_month()):
        assert asyncio.run(timer.tick())

    assert _config_of(child) == str(path)
    assert timer.snapshot().last_outcome == AutoOutcome.COMPLETED.value


@pytest.mark.feature("automation.web-honours-config")
def test_running_a_suggestion_runs_its_child_with_the_servers_config(alt_config, child) -> None:
    from immich_memories.automation.candidates import make_memory_key
    from immich_memories.web import mount_web
    from immich_memories.web.dependencies import current_config
    from tests.auto_library_fake import last_month

    path, config = alt_config
    app = FastAPI()
    mount_web(app)
    app.dependency_overrides[current_config] = lambda: config
    key = make_memory_key("monthly_highlights", *last_month())
    with immich_serving(library_with_last_month()):
        started = TestClient(app).post("/api/v1/suggestions/run", json={"memory_key": key})
        assert started.status_code == 202, started.text
        attempt_id = started.json()["id"]
        for _ in range(200):
            attempt = _attempt(config, attempt_id)
            if attempt is not None and attempt.outcome is not AutoOutcome.RUNNING:
                break
            asyncio.run(asyncio.sleep(0.05))

    assert _config_of(child) == str(path)
    assert attempt is not None and attempt.outcome is AutoOutcome.COMPLETED, attempt
