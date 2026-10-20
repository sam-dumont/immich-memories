"""An ACE-Step API poll survives a server that goes quiet for a moment, and says why it fails."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from immich_memories.audio.generators import ace_step_api_retry
from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig

_DONE = {
    "status": 1,
    "result": json.dumps([{"file": "/v1/audio?path=take.wav"}]),
}


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    async def instant(_seconds: float) -> None:
        return None

    # WHY: the backoff and the 3 s poll interval are real time; the tests are about the sequence.
    monkeypatch.setattr("asyncio.sleep", instant)


class _Server:
    """A fake ACE-Step server: scripted answers per route, in order."""

    def __init__(self, polls: list, downloads: list | None = None) -> None:
        self.polls = list(polls)
        self.downloads = list(downloads or [b"RIFFwav"])
        self.poll_calls = 0

    async def post(self, url: str, json: dict) -> httpx.Response:
        self.poll_calls += 1
        return self._answer(self.polls.pop(0) if len(self.polls) > 1 else self.polls[0], url)

    async def get(self, url: str) -> httpx.Response:
        item = self.downloads.pop(0) if len(self.downloads) > 1 else self.downloads[0]
        return self._answer(item, url)

    @staticmethod
    def _answer(item, url: str) -> httpx.Response:
        if isinstance(item, Exception):
            raise item
        request = httpx.Request("POST", url)
        if isinstance(item, int):
            return httpx.Response(item, request=request)
        if isinstance(item, bytes):
            return httpx.Response(200, content=item, request=request)
        return httpx.Response(200, json={"data": [item]}, request=request)


def _backend() -> ACEStepBackend:
    return ACEStepBackend(ACEStepConfig(mode="api", api_url="http://ace.invalid:8000"))


async def _poll(server: _Server, tmp_path: Path) -> Path:
    out = tmp_path / "take.wav"
    await _backend()._poll_and_download(server, "task-1", out, None)
    return out


async def test_a_poll_that_drops_the_connection_twice_still_ends_with_the_take(tmp_path):
    server = _Server([httpx.ReadError("eof"), httpx.RemoteProtocolError("closed"), _DONE])

    out = await _poll(server, tmp_path)

    assert out.read_bytes() == b"RIFFwav" and server.poll_calls == 3


@pytest.mark.parametrize("status", [502, 503])
async def test_a_proxy_5xx_on_a_poll_is_retried(tmp_path, status):
    out = await _poll(_Server([status, _DONE]), tmp_path)

    assert out.exists()


async def test_the_result_download_is_retried_too(tmp_path):
    server = _Server([_DONE], downloads=[httpx.ReadError("eof"), 503, b"RIFFwav"])

    assert (await _poll(server, tmp_path)).read_bytes() == b"RIFFwav"


async def test_a_server_that_keeps_failing_gives_up_within_the_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(ace_step_api_retry, "TRANSIENT_WINDOW_SECONDS", 0.0)
    server = _Server([httpx.ReadError("eof")])

    with pytest.raises(httpx.ReadError):
        await _poll(server, tmp_path)

    assert server.poll_calls == 1


async def test_a_reported_task_failure_is_not_retried(tmp_path):
    server = _Server([{"status": 2, "result": "[]"}])

    with pytest.raises(RuntimeError, match="failed"):
        await _poll(server, tmp_path)

    assert server.poll_calls == 1


async def test_a_4xx_is_not_retried(tmp_path):
    server = _Server([401])

    with pytest.raises(httpx.HTTPStatusError):
        await _poll(server, tmp_path)

    assert server.poll_calls == 1


async def test_the_health_probe_survives_one_dropped_connection(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **_kw): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a): ...
        async def get(self, url):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.ReadError("eof")
            return httpx.Response(
                200, json={"data": {"status": "ok"}}, request=httpx.Request("GET", url)
            )

    monkeypatch.setattr("httpx.AsyncClient", Client)  # WHY: the network boundary

    assert await _backend()._check_api() is True and len(calls) == 2


def test_a_failed_backend_logs_why_without_the_url(caplog):
    import asyncio

    from immich_memories.audio.music_pipeline import _run

    class Broken:
        name = "ACE-Step"

        async def generate(self, _request, _progress):
            raise httpx.ReadError("eof from http://ace.invalid:8000/query_result")

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(_run(Broken(), object(), lambda *_a: None))  # type: ignore[arg-type]

    assert result is None
    assert "failed (ReadError)" in caplog.text and "ace.invalid" not in caplog.text


def test_a_task_the_server_reports_failed_logs_that_reason(caplog):
    import asyncio

    from immich_memories.audio.generators.base import GenerationFailure
    from immich_memories.audio.music_pipeline import _run

    class Failing:
        name = "ACE-Step"

        async def generate(self, _request, _progress):
            raise GenerationFailure(
                "task t1 failed: {...}", reason="the server reported the task failed (status 2)"
            )

    with caplog.at_level(logging.WARNING):
        asyncio.run(_run(Failing(), object(), lambda *_a: None))  # type: ignore[arg-type]

    assert "the server reported the task failed (status 2)" in caplog.text
