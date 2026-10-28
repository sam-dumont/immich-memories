"""LLM calls as OpenTelemetry GenAI client spans: what was asked, what it cost, how it ended.

One span per logical call (`chat {model}`, kind CLIENT), covering every attempt the transport
makes, as the GenAI semantic conventions ask. Token counts arrive through
`llm_metrics.record_reply`, which every dialect already calls with what the server billed;
finish reasons and attempts arrive through the transport observer.

The prompt and the reply carry people's names and captions, so they are recorded only when
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`, the switch the OpenTelemetry GenAI
instrumentations share. Pictures never are, only how many went in.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from opentelemetry.trace import SpanKind

from immich_memories.tracking import otel

# The conventions' discriminator says which telemetry flavour the provider speaks; every
# OpenAI-compatible server speaks OpenAI's.
_PROVIDERS = {"openai-compatible": "openai"}
# A whole editorial prompt is tens of kilobytes; past this, a trace store pays for little.
_CONTENT_CHARACTERS = 100_000


@dataclass
class Call:
    """One logical LLM call in flight: the totals its attempts add up to."""

    span: otel.Span
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    finish_reasons: list[str] = field(default_factory=list)

    def billed(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        reasoning_tokens: int,
        model: str | None,
        response_id: str | None,
    ) -> None:
        """Add one attempt's bill; retries cost too, so the span shows what the call cost."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.reasoning_tokens += reasoning_tokens
        usage = {
            "gen_ai.usage.input_tokens": self.input_tokens,
            "gen_ai.usage.output_tokens": self.output_tokens,
            "gen_ai.usage.cache_read.input_tokens": self.cache_read_tokens or None,
            "gen_ai.usage.reasoning.output_tokens": self.reasoning_tokens or None,
            "gen_ai.response.model": model,
            "gen_ai.response.id": response_id,
        }
        self.span.set_attributes({key: value for key, value in usage.items() if value is not None})

    def attempt(
        self, *, number: int, outcome: str, status_code: int | None, finish_reason: str | None
    ) -> None:
        """One HTTP attempt as an event, and its finish reason when it got that far."""
        details: dict[str, str | int | None] = {
            "gen_ai.attempt": number,
            "outcome": outcome,
            "http.response.status_code": status_code,
            "gen_ai.response.finish_reason": finish_reason,
        }
        self.span.add_event(
            "gen_ai.attempt", {key: value for key, value in details.items() if value is not None}
        )
        if finish_reason:
            self.finish_reasons.append(finish_reason)
            self.span.set_attribute("gen_ai.response.finish_reasons", self.finish_reasons)

    def failed(self, error_type: str) -> None:
        """Fail the call for an error the caller handled instead of raising."""
        self.span.set_attribute("error.type", error_type)
        otel.mark_failed(self.span, error_type, "the LLM call failed")

    def answered(self, text: str) -> None:
        """The reply, when content capture is on."""
        if not capturing():
            return
        message: dict[str, Any] = {
            "role": "assistant",
            "parts": [{"type": "text", "content": text[:_CONTENT_CHARACTERS]}],
        }
        if self.finish_reasons:
            message["finish_reason"] = self.finish_reasons[-1]
        self.span.set_attribute("gen_ai.output.messages", json.dumps([message]))


_call: ContextVar[Call | None] = ContextVar("genai_call", default=None)


def current() -> Call | None:
    """The call the code running now is part of, for the transport to report into."""
    return _call.get()


def capturing() -> bool:
    """Whether prompts and replies go into the trace (off unless the standard switch says so)."""
    flag = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "")
    return flag.strip().lower() == "true"


@contextmanager
def inference(
    *,
    provider: str,
    model: str,
    base_url: str,
    prompt: str | None,
    stage: str | None,
    images: int = 0,
    batch: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_output: bool = False,
    thinking: bool = False,
) -> Iterator[Call]:
    """A `chat {model}` client span around one logical call, current for what runs inside."""
    server = urlsplit(base_url)
    attributes = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": _PROVIDERS.get(provider, provider),
        "gen_ai.request.model": model,
        "gen_ai.request.temperature": temperature,
        "gen_ai.request.max_tokens": max_tokens,
        "gen_ai.output.type": "json" if json_output else None,
        "server.address": server.hostname,
        "server.port": server.port,
        "immich_memories.llm.stage": stage,
        "immich_memories.llm.images": images or None,
        "immich_memories.llm.thinking": thinking or None,
        "immich_memories.llm.batch": batch or None,
    }
    if capturing() and prompt is not None:
        part = {"type": "text", "content": prompt[:_CONTENT_CHARACTERS]}
        attributes["gen_ai.input.messages"] = json.dumps([{"role": "user", "parts": [part]}])
    span = otel.start(f"chat {model}", attributes, kind=SpanKind.CLIENT)
    call = Call(span)
    token = _call.set(call)
    try:
        with otel.current(span):
            yield call
    except BaseException as error:
        # The type only: a transport error's text names the server, which is a setting.
        call.failed(type(error).__name__)
        raise
    finally:
        _call.reset(token)
        otel.end(span)


def billed(usage: Mapping[str, Any]) -> None:
    """Report one attempt's bill to the call in flight, if there is one."""
    if (call := current()) is not None:
        call.billed(**usage)
