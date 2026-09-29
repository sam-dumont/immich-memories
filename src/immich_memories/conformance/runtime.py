"""Measure production feature calls without replacing their provider responses."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import httpx

from immich_memories.analysis.llm_metrics import collecting
from immich_memories.security import write_secret_file


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
    usage: dict[str, float | int] = field(default_factory=dict)
    observed: set[str] = field(default_factory=set, repr=False)

    @property
    def called(self) -> bool:
        return self.calls > 0


_MODEL_PATHS = ("/chat/completions", "/messages", "/api/generate")


def _wire_body(raw: bytes):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")


async def _record_exchange(root, name, number, request, response):
    if root is None or not request.url.path.endswith(_MODEL_PATHS):
        return
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    write_secret_file(
        root / slug / f"{number:03d}.private.json",
        json.dumps(
            {
                "request": _wire_body(request.content),
                "response": _wire_body(await response.aread()),
                "status": response.status_code,
            },
            indent=2,
        ),
    )


def run_case(case: Case, *, evidence_dir: Path | None = None) -> Result:
    result = Result(case.name)
    source = str(Path(__file__).resolve().parents[1]) + "/"
    original_send = httpx.AsyncClient.send

    async def counted_send(client, request, *args, **kwargs):
        is_model = request.url.path.endswith(_MODEL_PATHS)
        result.calls += int(is_model)
        number = result.calls
        response = await original_send(client, request, *args, **kwargs)
        await _record_exchange(evidence_dir, case.name, number, request, response)
        return response

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
        result.usage = usage.as_metrics()
        result.tokens = (
            None
            if usage.unmetered_calls or usage.calls < result.calls
            else usage.prompt_tokens + usage.completion_tokens
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
        tokens = "unknown" if row.tokens is None else str(row.tokens)
        lines.append(
            f"| {row.name} | {row.called} | {row.calls} | {tokens} | "
            f"{row.seconds:.2f} | {row.valid} | {quality} |"
        )
    return "\n".join(lines)
