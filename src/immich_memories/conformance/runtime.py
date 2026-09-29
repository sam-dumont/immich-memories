"""Measure production feature calls without replacing their provider responses."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import httpx

from immich_memories.analysis.llm_metrics import collecting


@dataclass(frozen=True)
class Case:
    name: str
    run: Callable[[], str]
    sites: frozenset[str]


@dataclass
class Result:
    name: str
    calls: int = 0
    tokens: int | None = 0
    seconds: float = 0
    valid: bool = False
    quality: str = ""
    observed: set[str] = field(default_factory=set, repr=False)

    @property
    def called(self) -> bool:
        return self.calls > 0


_MODEL_PATHS = ("/chat/completions", "/messages", "/api/generate")


def run_case(case: Case) -> Result:
    result = Result(case.name)
    source = str(Path(__file__).resolve().parents[1]) + "/"
    original_send = httpx.AsyncClient.send

    async def counted_send(client, request, *args, **kwargs):
        if request.url.path.endswith(_MODEL_PATHS):
            result.calls += 1
        return await original_send(client, request, *args, **kwargs)

    def observe(frame, event, _arg):
        filename = frame.f_code.co_filename
        if event == "call" and filename.startswith(source):
            module = filename[len(source) :].removesuffix(".py").replace("/", ".")
            name = frame.f_code.co_qualname.replace(".<locals>.", ".")
            result.observed.add(f"{module}:{name}")

    old_profile, old_thread_profile = sys.getprofile(), threading.getprofile()
    started = time.monotonic()
    with collecting() as usage, patch.object(httpx.AsyncClient, "send", counted_send):
        sys.setprofile(observe)
        threading.setprofile(observe)
        try:
            result.quality = case.run()
            result.valid = True
        except AssertionError as exc:
            result.quality = str(exc) or "feature quality assertion failed"
        except Exception as exc:  # Each failed provider feature must leave a table row.
            result.quality = type(exc).__name__
        finally:
            sys.setprofile(old_profile)
            threading.setprofile(old_thread_profile)
        result.tokens = (
            None if usage.unmetered_calls else usage.prompt_tokens + usage.completion_tokens
        )
    result.seconds = round(time.monotonic() - started, 2)
    missing = case.sites - result.observed
    if not result.called:
        result.valid = False
        result.quality = "feature made no provider request"
    elif missing:
        result.valid = False
        result.quality = "declared call sites were not exercised: " + ", ".join(sorted(missing))
    return result


def table(results: list[Result]) -> str:
    lines = [
        "| Feature | Called? | Calls | Tokens | Seconds | Valid? | Quality check |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in results:
        quality = row.quality.replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {row.name} | {row.called} | {row.calls} | {row.tokens} | "
            f"{row.seconds:.2f} | {row.valid} | {quality} |"
        )
    return "\n".join(lines)
