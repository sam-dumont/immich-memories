"""A restarted ACE-Step server forgets the task: resubmit once, then fall back at once."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig
from immich_memories.audio.generators.base import GenerationFailure, GenerationRequest

API_URL = "http://music.invalid:8000"


class _Reply:
    def __init__(self, data=None, content=b""):
        self._data = data
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


class FakeAceServer:
    """Speaks release_task / query_result / file download like the real server.

    ``forget_after`` is how many polls of a task get a real answer before the server
    "restarts" and answers like it never heard of the id; ``None`` means never forget.
    A task the server knows carries ``progress_text``; an unknown id does not.
    """

    def __init__(self, *, forget_after: int | None, finish_after: int = 100):
        self.forget_after = forget_after
        self.finish_after = finish_after
        self.submitted: list[dict] = []
        self.polls: dict[str, int] = {}
        self.always_forget = False
        # None = no /v1/stats endpoint (404); a dict or a callable returning one otherwise.
        self.stats = None
        self.stats_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kwargs):
        if url.endswith("/release_task"):
            self.submitted.append(json)
            return _Reply({"data": {"task_id": f"task-{len(self.submitted)}"}})
        task_id = json["task_id_list"][0]
        n = self.polls[task_id] = self.polls.get(task_id, 0) + 1
        if self.always_forget or (self.forget_after is not None and n > self.forget_after):
            return _Reply({"data": [{"task_id": task_id, "result": "[]", "status": 0}]})
        if n >= self.finish_after:
            result = _json_dumps([{"file": "/v1/audio?path=x.wav"}])
            return _Reply({"data": [{"task_id": task_id, "result": result, "status": 1}]})
        item = {"task_id": task_id, "result": "[]", "status": 0, "progress_text": "working"}
        return _Reply({"data": [item]})

    async def get(self, url, **kwargs):
        if url.endswith("/v1/stats"):
            self.stats_calls += 1
            if self.stats is None:
                request = httpx.Request("GET", url)
                raise httpx.HTTPStatusError(
                    "not found", request=request, response=httpx.Response(404, request=request)
                )
            return _Reply(self.stats() if callable(self.stats) else self.stats)
        return _Reply(content=b"RIFFwav")


def _json_dumps(value) -> str:
    return json.dumps(value)


def _generate(server: FakeAceServer, tmp_path: Path, sleeps: list[float]):
    backend = ACEStepBackend(ACEStepConfig(mode="api", api_url=API_URL, timeout_seconds=3600))
    backend._effective_mode = "api"
    request = GenerationRequest(prompt="happy", duration_seconds=30, output_dir=tmp_path)

    async def no_sleep(seconds):
        sleeps.append(seconds)

    # WHY: httpx is the network boundary; asyncio.sleep is the clock the poll loop waits on.
    with (
        patch("httpx.AsyncClient", return_value=server),
        patch("asyncio.sleep", no_sleep),
    ):
        return asyncio.run(backend._generate_api(request))


def test_task_forgotten_after_restart_is_resubmitted_and_film_gets_the_track(tmp_path):
    server = FakeAceServer(forget_after=2, finish_after=4)
    # The restarted server knows the second task: only the first id is forgotten.
    original_post = server.post

    async def post(url, json=None, **kwargs):
        if json and json.get("task_id_list") == ["task-2"]:
            server.forget_after = None
        return await original_post(url, json=json, **kwargs)

    server.post = post
    sleeps: list[float] = []

    result = _generate(server, tmp_path, sleeps)

    assert len(server.submitted) == 2
    assert server.submitted[0] == server.submitted[1]
    assert result.metadata["task_id"] == "task-2"
    assert result.audio_path.read_bytes() == b"RIFFwav"


def test_server_that_always_forgets_fails_fast_with_a_plain_reason(tmp_path, caplog):
    server = FakeAceServer(forget_after=0)
    server.always_forget = True
    sleeps: list[float] = []

    with caplog.at_level(logging.WARNING), pytest.raises(GenerationFailure) as err:
        _generate(server, tmp_path, sleeps)

    assert "restarted" in err.value.reason
    assert len(server.submitted) == 2
    assert sum(sleeps) < 60  # a handful of polls, not the 3600 s timeout
    warnings = [r.getMessage() for r in caplog.records if "lost" in r.getMessage()]
    assert warnings
    assert all("music.invalid" not in m for m in warnings)


def test_one_stray_unknown_reply_does_not_count_as_a_lost_task(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=6)
    original_post = server.post
    state = {"n": 0}

    async def post(url, json=None, **kwargs):
        if json and "task_id_list" in json:
            state["n"] += 1
            if state["n"] == 2:
                tid = json["task_id_list"][0]
                return _Reply({"data": [{"task_id": tid, "result": "[]", "status": 0}]})
        return await original_post(url, json=json, **kwargs)

    server.post = post
    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert result.metadata["task_id"] == "task-1"


def test_running_task_with_progress_text_keeps_polling_until_done(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    sleeps: list[float] = []

    result = _generate(server, tmp_path, sleeps)

    assert len(server.submitted) == 1
    assert server.polls["task-1"] == 25
    assert len(sleeps) == 24
    assert result.audio_path.exists()


def _stats(queued=0, running=0, queue_size=0):
    return {
        "data": {
            "jobs": {"total": 0, "queued": queued, "running": running},
            "queue_size": queue_size,
        },
        "code": 200,
    }


def _server_that_knows_task_2(server: FakeAceServer) -> None:
    """The restarted server runs the resubmitted task for real: it finishes after 3 polls."""
    original_post = server.post

    async def post(url, json=None, **kwargs):
        if json and json.get("task_id_list") == ["task-2"]:
            server.forget_after = None
            server.finish_after = 3
            server.stats = _stats(running=1)
        return await original_post(url, json=json, **kwargs)

    server.post = post


def test_cached_running_task_absent_from_stats_is_resubmitted(tmp_path):
    # The first task answers status 0 with progress_text forever, as the server's cache does.
    server = FakeAceServer(forget_after=None)
    server.stats = _stats()
    _server_that_knows_task_2(server)

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 2
    assert result.metadata["task_id"] == "task-2"
    assert server.polls["task-1"] < 10


def test_cached_task_that_stays_dead_fails_after_one_resubmit(tmp_path):
    server = FakeAceServer(forget_after=None)
    server.stats = _stats()
    sleeps: list[float] = []

    with pytest.raises(GenerationFailure) as err:
        _generate(server, tmp_path, sleeps)

    assert "restarted" in err.value.reason
    assert len(server.submitted) == 2
    assert sum(sleeps) < 60


def test_task_queued_behind_another_job_is_not_treated_as_lost(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    server.stats = _stats(queued=1, queue_size=1)

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert server.stats_calls > 0
    assert result.metadata["task_id"] == "task-1"


def test_running_job_in_stats_is_not_treated_as_lost(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    server.stats = _stats(running=1)

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert result.metadata["task_id"] == "task-1"


def test_one_idle_stats_reading_does_not_count_as_lost(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    readings = iter([_stats()])
    server.stats = lambda: next(readings, _stats(running=1))

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert result.metadata["task_id"] == "task-1"


def test_server_without_stats_endpoint_keeps_polling_a_cached_task(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    server.stats = None

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert server.polls["task-1"] == 25
    assert result.metadata["task_id"] == "task-1"


def test_stats_with_unexpected_shape_keeps_old_behaviour(tmp_path):
    server = FakeAceServer(forget_after=None, finish_after=25)
    server.stats = {"unexpected": True}

    result = _generate(server, tmp_path, [])

    assert len(server.submitted) == 1
    assert result.metadata["task_id"] == "task-1"
