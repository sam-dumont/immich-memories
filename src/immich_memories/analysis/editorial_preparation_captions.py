"""Portable compact-v3 caption requests, sharing the accepted wire and outcome contract."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import asdict, dataclass, replace
from http.client import HTTPResponse
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image

from immich_memories.analysis import editorial_description_outcomes as caption_outcomes
from immich_memories.analysis.editorial_async_bridge import _run_sync
from immich_memories.analysis.editorial_description_contract import (
    API_MODEL,
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
    MAX_OUTPUT_TOKENS,
    PROMPT,
    RESPONSE_SCHEMA,
    DescriptionEnvelope,
)
from immich_memories.analysis.editorial_description_contract import (
    validate_envelope as _validate_envelope,
)
from immich_memories.analysis.editorial_description_wire import (
    request_payload as _wire_payload,
)
from immich_memories.analysis.editorial_description_wire import (
    tile_preview,
)
from immich_memories.analysis.llm_caption_identity import (
    LLM_DESCRIPTION_SOURCE,
    llm_caption_identity,
)
from immich_memories.analysis.llm_metrics import record_reply, recording_stage
from immich_memories.analysis.llm_preparation_usage import record_preparation_attempt
from immich_memories.analysis.llm_providers import resolved_llm_config
from immich_memories.analysis.llm_query import query_llm
from immich_memories.config_models_llm import LLMConfig
from immich_memories.store.caption_provenance import (
    CaptionOrigin,
    remember_origin,
    served_facts,
)
from immich_memories.store.editorial_preparation import now

REFUSED_CODES = frozenset({401, 403})
_REFUSED_ERRORS = tuple(f"http_{code}" for code in sorted(REFUSED_CODES))
CAPTION_KEY_HINT = (
    "set advanced.editorial.preparation.caption_api_key "
    "(IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_API_KEY)"
)


def _request_payload(image: bytes, *, api_model: str) -> dict[str, object]:
    return _wire_payload(image, api_model=api_model)


@dataclass(frozen=True, slots=True)
class CallOutcome:
    envelope: DescriptionEnvelope | None
    error: str | None
    elapsed_seconds: float
    finish_reason: str | None
    completion_tokens: int | None
    prompt_tokens: int | None
    raw_sha256: str | None
    raw_content: str | None = None
    request_sha256: str | None = None
    image_sha256: str | None = None


def bearer_headers(api_key: str) -> dict[str, str]:
    """The Authorization header a protected caption endpoint needs, or nothing at all.

    An empty key leaves the request exactly as it was, so an unauthenticated
    server on localhost never sees a header it would have to ignore.
    """
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port


class _CredentialsStayOnTheirOrigin(urllib.request.HTTPRedirectHandler):
    """urllib copies every header onto a redirect, Authorization included (#1212)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        follow = super().redirect_request(req, fp, code, msg, headers, newurl)
        if follow is not None and _origin(newurl) != _origin(req.full_url):
            follow.remove_header("Authorization")
        return follow


_OPENER = urllib.request.build_opener(_CredentialsStayOnTheirOrigin)


def open_caption_url(request: urllib.request.Request, *, timeout: float) -> HTTPResponse:
    """urlopen for a caption endpoint: a redirect to another origin loses the bearer token."""
    return _OPENER.open(request, timeout=timeout)


def _model_inventory(base_url: str, *, timeout: float, api_key: str) -> list[dict]:
    request = urllib.request.Request(f"{base_url}/models", headers=bearer_headers(api_key))  # noqa: S310
    try:
        with open_caption_url(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code not in REFUSED_CODES:
            raise
        # The endpoint is there and answering; it wants a credential. Another URL is not the fix.
        raise PermissionError(
            f"caption endpoint {base_url} answered HTTP {exc.code}; {CAPTION_KEY_HINT}"
        ) from exc
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("public description endpoint returned no model inventory")
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]


def _ask_one(
    base_url: str, image: bytes, *, timeout: float, api_key: str, stage: str = "caption"
) -> CallOutcome:
    wire = json.dumps(_request_payload(image, api_model=API_MODEL)).encode()
    request = urllib.request.Request(  # noqa: S310
        f"{base_url}/chat/completions",
        data=wire,
        headers={"Content-Type": "application/json"} | bearer_headers(api_key),
    )
    request_sha256 = hashlib.sha256(wire).hexdigest()
    image_sha256 = hashlib.sha256(image).hexdigest()
    raw_content: str | None = None
    started = time.monotonic()
    finish_reason: str | None = None
    raw_sha256: str | None = None
    completion_tokens: int | None = None
    prompt_tokens: int | None = None
    body: object = None
    try:
        with open_caption_url(request, timeout=timeout) as response:
            body = json.loads(response.read())
        if not isinstance(body, dict):
            raise ValueError("caption response is not an object")
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        completion_tokens = _optional_int(usage.get("completion_tokens"))
        prompt_tokens = _optional_int(usage.get("prompt_tokens"))
        choice = body["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("model content is not text")
        raw_content = content
        raw_sha256 = hashlib.sha256(content.encode()).hexdigest()
        if finish_reason != "stop":
            raise ValueError(f"model finish reason is {finish_reason!r}")
        envelope = _validate_envelope(json.loads(content))
        return CallOutcome(
            envelope=envelope,
            error=None,
            elapsed_seconds=time.monotonic() - started,
            finish_reason=finish_reason,
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            raw_sha256=raw_sha256,
            raw_content=raw_content,
            request_sha256=request_sha256,
            image_sha256=image_sha256,
        )
    except urllib.error.HTTPError as exc:
        error = f"http_{exc.code}"
        if exc.code in REFUSED_CODES:
            error = f"{error}; {CAPTION_KEY_HINT}"
    except json.JSONDecodeError:
        error = "unparsed"
    except (KeyError, TypeError, ValueError) as exc:
        error = f"invalid:{exc}"
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        error = type(exc).__name__
    finally:
        record_preparation_attempt(body, stage=stage, elapsed_seconds=time.monotonic() - started)
    return CallOutcome(
        envelope=None,
        error=error,
        elapsed_seconds=time.monotonic() - started,
        finish_reason=finish_reason,
        completion_tokens=completion_tokens,
        prompt_tokens=prompt_tokens,
        raw_sha256=raw_sha256,
        raw_content=raw_content,
        request_sha256=request_sha256,
        image_sha256=image_sha256,
    )


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def ask_llm_image(
    config: LLMConfig,
    image: bytes,
    *,
    prompt: str,
    response_format: Mapping[str, Any],
    timeout: float,
    stage: str,
) -> str:
    """Use the configured provider's vision transport and bill the image producer's stage."""
    with recording_stage(stage):
        try:
            return _run_sync(
                query_llm(
                    prompt,
                    config,
                    temperature=0.0,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    timeout_seconds=int(timeout),
                    thinking=False,
                    images=(image,),
                    image_detail="high",
                    require_complete=True,
                    response_format=response_format,
                )
            )
        except httpx.HTTPStatusError as exc:
            # The shared transport records completed replies after this HTTP check.
            record_reply(stage=stage, usage_known=False)
            if exc.response.status_code not in REFUSED_CODES:
                raise
            raise PermissionError(
                f"configured LLM endpoint answered HTTP {exc.response.status_code}; "
                "set advanced.llm.api_key"
            ) from exc


def _ask_llm(
    config: LLMConfig, image: bytes, *, timeout: float, stage: str = "caption"
) -> CallOutcome:
    started = time.monotonic()
    raw = None
    error = None
    envelope = None
    try:
        raw = ask_llm_image(
            config,
            image,
            prompt=PROMPT,
            timeout=timeout,
            stage=stage,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "compact_asset_description",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            },
        )
        envelope = _validate_envelope(json.loads(raw))
    except PermissionError:
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return CallOutcome(
        envelope=envelope,
        error=error,
        elapsed_seconds=time.monotonic() - started,
        finish_reason="stop" if raw is not None else None,
        completion_tokens=None,
        prompt_tokens=None,
        raw_sha256=hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None,
        raw_content=raw,
        image_sha256=hashlib.sha256(image).hexdigest(),
    )


def check_provider(
    base_url: str,
    timeout: float,
    check_cancelled: Callable[[], None],
    *,
    api_key: str = "",
    llm_config: LLMConfig | None = None,
) -> CaptionOrigin:
    """Accept the endpoint, and describe the build behind it out of its own answers.

    The alias and the URL are configuration: every shipped recipe advertises the
    same alias on the same port, so neither separates mlxcel from llama.cpp. The
    served `/models` row and the three schema controls are the two things here
    that came out of the weights. Measured against both captioners this project
    ships a recipe for, serving the same 500M model: mlxcel answers
    `owned_by=user` and no `meta`, llama.cpp answers `owned_by=llamacpp`,
    `meta.ftype=Q8_0`, `meta.n_params=409252800`, and the control digests are
    f5a1cdf9df7fe125 against 824e389c39e457a6 — each stable across repeats,
    different between the two. The digest is the load-bearing half: two builds
    that word `setting` the same way are not a harmful mix, and two that word it
    differently cannot hide behind one alias on one port.
    """
    check_cancelled()
    model_id = API_MODEL
    served = {}
    if llm_config is not None:
        resolved = resolved_llm_config(llm_config)
        base_url, model_id = resolved.base_url, resolved.model
    else:
        inventory = _model_inventory(base_url, timeout=timeout, api_key=api_key)
        advertised = next((row for row in inventory if row["id"] == API_MODEL), None)
        if advertised is None:
            raise ValueError(f"caption endpoint must advertise {API_MODEL}")
        served = served_facts(advertised)
    # Preserve the accepted three schema controls before sending library previews.
    answers = []
    for rgb in ((200, 20, 20), (20, 40, 200), (128, 128, 128)):
        check_cancelled()
        buffer = io.BytesIO()
        Image.new("RGB", (400, 400), rgb).save(buffer, "JPEG", quality=90)
        image = tile_preview(buffer.getvalue())
        control = (
            _ask_llm(llm_config, image, timeout=timeout, stage="caption_controls")
            if llm_config is not None
            else _ask_one(
                base_url, image, timeout=timeout, api_key=api_key, stage="caption_controls"
            )
        )
        if control.envelope is None:
            # A refused control says nothing about the schema; it never reached it.
            if control.error and control.error.startswith(_REFUSED_ERRORS):
                raise PermissionError(f"caption endpoint {base_url}: {control.error}")
            raise ValueError("caption endpoint failed the compact-v3 schema control")
        answers.append(control.raw_sha256 or "")
    control_digest = hashlib.sha256("|".join(answers).encode()).hexdigest()[:16]
    return CaptionOrigin(
        model_id=model_id,
        endpoint=base_url,
        served=served,
        control_digest=control_digest,
    )


def _describe(
    asset_id: str,
    *,
    preview_for: Callable[[str], bytes],
    base_url: str,
    timeout: float,
    api_key: str,
    check_cancelled: Callable[[], None],
    llm_config: LLMConfig | None = None,
) -> tuple[str, bytes, tuple[CallOutcome, ...]]:
    check_cancelled()
    preview = preview_for(asset_id)
    image = tile_preview(preview)
    outcomes = []
    for _attempt in range(2):
        check_cancelled()
        outcome = (
            _ask_llm(llm_config, image, timeout=timeout)
            if llm_config is not None
            else _ask_one(base_url, image, timeout=timeout, api_key=api_key)
        )
        outcomes.append(outcome)
        if outcome.envelope is not None:
            break
    return asset_id, preview, tuple(outcomes)


def prepare_captions(
    *,
    connection: sqlite3.Connection,
    asset_ids: Sequence[str],
    preview_for: Callable[[str], bytes],
    base_url: str,
    timeout: float,
    concurrency: int,
    check_cancelled: Callable[[], None],
    progress: Callable[[str, int, int], None],
    api_key: str = "",
    artifact_id: str = "",
    llm_config: LLMConfig | None = None,
) -> dict[str, str]:
    """Bank successes and only verified two-completion failures, with bounded concurrency."""
    if not asset_ids:
        return {}
    description_model = (
        llm_caption_identity(llm_config, artifact_id) if llm_config else DESCRIPTION_MODEL
    )
    origin = replace(
        check_provider(base_url, timeout, check_cancelled, api_key=api_key, llm_config=llm_config),
        artifact_id=artifact_id,
    )
    failures = {}
    # Bound submitted work too: cancellation must not drain a whole library queue.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(asset_ids), concurrency):
            check_cancelled()
            futures = [
                pool.submit(
                    copy_context().run,
                    _describe,
                    asset_id,
                    preview_for=preview_for,
                    base_url=base_url,
                    timeout=timeout,
                    api_key=api_key,
                    check_cancelled=check_cancelled,
                    llm_config=llm_config,
                )
                for asset_id in asset_ids[start : start + concurrency]
            ]
            for asset_id, future in zip(
                asset_ids[start : start + concurrency], futures, strict=True
            ):
                try:
                    _asset_id, preview, outcomes = future.result()
                    failure = _settle_caption(
                        connection,
                        asset_id,
                        preview,
                        outcomes,
                        origin,
                        model=description_model,
                        llm=llm_config is not None,
                    )
                    if failure:
                        failures[asset_id] = failure
                except Exception as exc:
                    failures[asset_id] = f"{type(exc).__name__}: {exc}"
            progress("captions", min(start + concurrency, len(asset_ids)), len(asset_ids))
    return failures


def _settle_caption(
    connection: sqlite3.Connection,
    asset_id: str,
    preview: bytes,
    outcomes: Sequence[CallOutcome],
    origin: CaptionOrigin,
    *,
    model: str,
    llm: bool,
) -> str | None:
    outcome = outcomes[-1]
    if outcome.envelope is not None:
        _remember_caption(
            connection,
            asset_id,
            outcome.envelope,
            origin,
            model=model,
            source=LLM_DESCRIPTION_SOURCE if llm else DESCRIPTION_SOURCE,
        )
        return None
    if not llm and caption_outcomes.bounded_invalid_attempts([asdict(o) for o in outcomes]):
        row = caption_outcomes.make_unavailable(
            asset_id, preview, [asdict(o) for o in outcomes], written_at=now()
        )
        caption_outcomes.remember_unavailable(connection, row, preview)
        return None
    return outcome.error or "caption failed without bounded completion evidence"


def _remember_caption(
    connection: sqlite3.Connection,
    asset_id: str,
    envelope: DescriptionEnvelope,
    origin: CaptionOrigin | None = None,
    *,
    model: str = DESCRIPTION_MODEL,
    source: str = DESCRIPTION_SOURCE,
) -> None:
    # Partial/conflicting rows are an integrity failure, never silently overwritten.
    timestamp = now()
    with connection:
        connection.execute(
            "INSERT INTO descriptions (asset_id,model,text,source,written_at) VALUES (?,?,?,?,?)",
            (asset_id, model, envelope.description, source, timestamp),
        )
        connection.execute(
            "INSERT INTO description_fields (asset_id,model,field,value,written_at) VALUES (?,?,?,?,?)",
            (asset_id, model, "setting", envelope.setting, timestamp),
        )
        if origin is not None:
            remember_origin(connection, asset_id, model, origin)
