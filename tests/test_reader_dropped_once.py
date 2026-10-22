"""A reader that drops every connection is given up on once per run, not once per question.

Measured on a real run: the reader's host accepted connections and dropped them, and the
episode reads asked it again for each of 87 events, three tries each, 13 seconds a question.
Twenty minutes went by before the film fell back to the rules it ended on anyway.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import replace

import httpx
import pytest

from immich_memories.analysis.judgments.text_gateway import SyncTextPromptRequester
from immich_memories.analysis.llm import query
from immich_memories.analysis.llm.wire import TRANSPORT_RETRIES
from immich_memories.config.models.llm import LLMConfig


class DroppingHost:
    """A loopback server that accepts every connection and closes it unanswered."""

    def __init__(self) -> None:
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self.port = self._socket.getsockname()[1]
        self.accepted = 0
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            self.accepted += 1
            connection.recv(65536)
            connection.close()

    def close(self) -> None:
        self._socket.close()


@pytest.fixture
def dropping_host(monkeypatch):
    """# WHY: skip the transport retries' real waits; the dropped connections stay real."""

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(query.asyncio, "sleep", no_wait)
    monkeypatch.setattr(query, "_WARNED_UNREACHABLE", set())
    host = DroppingHost()
    yield host
    host.close()


def _requester(port: int) -> SyncTextPromptRequester:
    config = LLMConfig(enabled=True, base_url=f"http://127.0.0.1:{port}/v1", model="model-a")
    return SyncTextPromptRequester(config, max_tokens=200, timeout_seconds=30)


def test_after_the_first_give_up_no_question_waits_on_the_dropped_host(dropping_host) -> None:
    ask = _requester(dropping_host.port)

    with pytest.raises(httpx.TransportError):
        ask("first event")
    tried = dropping_host.accepted
    for event in range(5):
        with pytest.raises(httpx.TransportError):
            ask(f"event {event}")

    assert tried == TRANSPORT_RETRIES
    assert dropping_host.accepted == tried


def test_a_copy_made_for_the_run_record_remembers_the_same_dead_host(dropping_host) -> None:
    """The run wraps its requester with `dataclasses.replace` to keep its transcript."""
    ask = _requester(dropping_host.port)
    recorded = replace(ask, retry_larger=False)

    with pytest.raises(httpx.TransportError):
        recorded("first event")
    tried = dropping_host.accepted
    with pytest.raises(httpx.TransportError):
        ask("second event")

    assert dropping_host.accepted == tried


def test_a_refused_request_is_not_a_dead_host(monkeypatch) -> None:
    """A server that answers, even with an error about the request, is still there."""
    from immich_memories.analysis.judgments import text_gateway

    calls = []

    async def refuses(prompt, *_args, **_kwargs):
        calls.append(prompt)
        raise ValueError("the server read the request and refused it")

    monkeypatch.setattr(text_gateway, "query_llm", refuses)
    ask = SyncTextPromptRequester(
        LLMConfig(enabled=True, base_url="http://reader.test/v1", model="model-a"),
        max_tokens=200,
        timeout_seconds=30,
        retry_larger=False,
    )

    for event in ("one", "two"):
        with pytest.raises(ValueError):
            ask(event)

    assert calls == ["one", "two"]
