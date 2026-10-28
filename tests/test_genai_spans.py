"""Every LLM call is a GenAI semantic-convention span, with its tokens, on the real HTTP path."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from immich_memories.tracking import otel, timing
from tests.otel_receiver import receiving

_CLIENT = 3  # SpanKind.CLIENT on the OTLP wire
_ERROR = 2


class _Provider(BaseHTTPRequestHandler):
    """An OpenAI-compatible server: answers with usage, or fails as told."""

    replies: list[tuple[int, dict]] = []
    seen: list[dict] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append(body)
        status, reply = self.replies.pop(0) if self.replies else (200, _reply("ok"))
        if status == 0:
            # Hang up without a reply: the transport sees a dropped connection and retries.
            self.close_connection = True
            return
        payload = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def _reply(content: str, *, finish: str = "stop") -> dict:
    return {
        "id": "chatcmpl-42",
        "model": "gemma-served",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens_details": {"reasoning_tokens": 12},
        },
    }


@pytest.fixture
def provider():
    _Provider.replies = []
    _Provider.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()
    server.server_close()


@pytest.fixture
def collector(monkeypatch):
    with receiving(monkeypatch) as received:
        otel.setup()
        yield received


def _config(port: int):
    from immich_memories.config.models.llm import LLMConfig

    return LLMConfig(
        enabled=True,
        provider="openai-compatible",
        base_url=f"http://127.0.0.1:{port}/v1",
        model="gemma-asked",
    )


def _ask(port: int, prompt: str = "Title this day", **kwargs) -> str:
    from immich_memories.analysis.llm.async_bridge import run_sync
    from immich_memories.analysis.llm.metrics import recording_stage
    from immich_memories.analysis.llm.query import query_llm

    with recording_stage("titles"), timing.span("selection.titles"):
        return run_sync(query_llm(prompt, _config(port), **kwargs))


def test_a_reader_call_is_a_client_chat_span_with_its_tokens(collector, provider):
    answer = _ask(
        provider,
        temperature=0.2,
        max_tokens=64,
        response_format={"type": "json_schema", "json_schema": {"name": "t", "schema": {}}},
    )

    assert answer == "ok"
    span = collector.named()["chat gemma-asked"]
    attributes = span["attributes"]
    assert span["kind"] == _CLIENT
    assert span["parent"] is not None
    assert attributes["gen_ai.operation.name"] == "chat"
    assert attributes["gen_ai.provider.name"] == "openai"
    assert attributes["gen_ai.request.model"] == "gemma-asked"
    assert attributes["gen_ai.response.model"] == "gemma-served"
    assert attributes["gen_ai.response.id"] == "chatcmpl-42"
    assert attributes["gen_ai.response.finish_reasons"] == ["stop"]
    assert attributes["gen_ai.request.temperature"] == 0.2
    assert attributes["gen_ai.request.max_tokens"] == 64
    assert attributes["gen_ai.output.type"] == "json"
    assert attributes["gen_ai.usage.input_tokens"] == 120
    assert attributes["gen_ai.usage.output_tokens"] == 30
    assert attributes["gen_ai.usage.cache_read.input_tokens"] == 100
    assert attributes["gen_ai.usage.reasoning.output_tokens"] == 12
    assert attributes["server.address"] == "127.0.0.1"
    assert attributes["server.port"] == provider
    assert attributes["immich_memories.llm.stage"] == "titles"
    assert "gen_ai.input.messages" not in attributes
    assert "gen_ai.output.messages" not in attributes


def test_prompt_and_reply_are_recorded_only_when_capture_is_on(collector, provider, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

    _ask(provider, prompt="Title the beach day")

    attributes = collector.named()["chat gemma-asked"]["attributes"]
    asked = json.loads(attributes["gen_ai.input.messages"])
    answered = json.loads(attributes["gen_ai.output.messages"])
    assert asked == [
        {"role": "user", "parts": [{"type": "text", "content": "Title the beach day"}]}
    ]
    assert answered == [
        {
            "role": "assistant",
            "parts": [{"type": "text", "content": "ok"}],
            "finish_reason": "stop",
        }
    ]


def test_a_retried_call_is_one_span_with_each_attempt_as_an_event(collector, provider):
    _Provider.replies = [(0, {}), (200, _reply("ok"))]

    assert _ask(provider) == "ok"

    spans = [span for span in collector.spans() if span["name"] == "chat gemma-asked"]
    assert len(spans) == 1
    attempts = [attributes for name, attributes in spans[0]["events"] if name == "gen_ai.attempt"]
    assert attempts[0]["outcome"] == "connection_error"
    assert attempts[-1]["gen_ai.response.finish_reason"] == "stop"
    assert spans[0]["status"] != _ERROR


def test_a_failed_call_names_its_error_type_and_no_server_details(collector, monkeypatch):
    from immich_memories.analysis.llm import query as query_module

    # Nothing listens on port 9: every attempt is refused.
    monkeypatch.setattr(query_module, "TRANSPORT_RETRIES", 1)
    with pytest.raises(Exception):  # noqa: B017, PT011 - whichever transport error httpx raises
        _ask(9)

    span = collector.named()["chat gemma-asked"]
    assert span["status"] == _ERROR
    assert span["attributes"]["error.type"] == "ConnectError"
    assert "127.0.0.1:9" not in json.dumps(span["events"])


def test_without_tracing_a_call_records_nothing_and_still_answers(provider, monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.shutdown()
    assert _ask(provider) == "ok"


def test_a_caption_worker_call_is_a_chat_span_too(collector, provider):
    from immich_memories.analysis.captions.requests import _ask_one

    _Provider.replies = [(200, _reply(json.dumps({"description": "a dog"})))]

    with timing.span("analysis.captions"):
        _ask_one(f"http://127.0.0.1:{provider}/v1", b"\xff\xd8jpeg", timeout=5, api_key="")

    spans = [span for span in collector.spans() if span["name"].startswith("chat ")]
    assert len(spans) == 1
    attributes = spans[0]["attributes"]
    assert spans[0]["kind"] == _CLIENT
    assert attributes["gen_ai.usage.input_tokens"] == 120
    assert attributes["gen_ai.response.finish_reasons"] == ["stop"]
    assert attributes["immich_memories.llm.images"] == 1


def test_each_answered_batch_line_is_its_own_chat_span(collector, provider):
    from immich_memories.analysis.llm.batch import _openai_result, _read_results

    line = {"custom_id": "k1", "response": {"status_code": 200, "body": _reply("batched")}}

    answers = _read_results(_config(provider), json.dumps(line), _openai_result)

    assert answers["k1"].content == "batched"
    span = collector.named()["chat gemma-asked"]
    assert span["attributes"]["immich_memories.llm.batch"] is True
    assert span["attributes"]["gen_ai.usage.input_tokens"] == 120
    assert span["attributes"]["gen_ai.response.id"] == "chatcmpl-42"
    assert span["attributes"]["gen_ai.response.finish_reasons"] == ["stop"]
