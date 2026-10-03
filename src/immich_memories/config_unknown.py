"""Key-only diagnostics for settings that the nested models ignore."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

# Process/service controls are consumed outside the settings models.
_PROCESS_KEYS = frozenset(
    {
        "ACESTEP_MLX_DIT_FP32",
        "ALLOW_LINK_LOCAL_URLS",
        "ALLOW_NETWORK_SQLITE",
        "AUTH_PASSWORD",
        "AUTH_USERNAME",
        "CONFIG",
        "DATABASE_SCHEMA",
        "DATABASE_URL",
        "DEPLOYMENT_CAPTION_URL",
        "DEPLOYMENT_GPU_BOX",
        "DEPLOYMENT_INFERENCE_URL",
        "DEPLOYMENT_READER_API_KEY",
        "DEPLOYMENT_READER_ENABLED",
        "DEPLOYMENT_READER_MODEL",
        "DEPLOYMENT_READER_URL",
        "DEPLOYMENT_TIER",
        "E2E_DATABASE_URL",
        "FONTS_DIR",
        "IMPORT_FROM",
        "INFERENCE_ALLOW_MODEL_DOWNLOADS",
        "INFERENCE_IDLE_UNLOAD_SECONDS",
        "INFERENCE_BUNDLE",
        "INFERENCE_REQUEST_THREADS",
        "INFERENCE_PRELOAD",
        "INFERENCE_MAX_QUEUED_REQUESTS",
        "INFERENCE_MAX_IMAGE_BYTES",
        "RENDER_WORKER_MAX_JOBS",
        "RENDER_WORKER_RETENTION_SECONDS",
        "RENDER_WORKER_JOB_TIMEOUT_SECONDS",
        "INFERENCE_CACHE_DIR",
        "INFERENCE_DETECTOR_CACHE_DIR",
        "INFERENCE_ENCODER",
        "INFERENCE_HOST",
        "INFERENCE_MARQO_ONNX",
        "INFERENCE_PORT",
        "INFERENCE_PROVIDER",
        "LOG_FILE",
        "LOG_FORMAT",
        "LOG_LEVEL",
        "OWNER",
        "RENDER_WORKER_DIRECTORY",
        "RENDER_WORKER_GEOCODING_URL",
        "RENDER_WORKER_HOST",
        "RENDER_WORKER_IMMICH_URL",
        "RENDER_WORKER_PORT",
        "RENDER_WORKER_TOKEN",
        "SECRET_KEY",
        "SELECTION_TRACE",
        "SKIP_STORED_SETTINGS",
        "STORAGE_SECRET",
        "TEST_DATABASE_URL",
    }
)


def _model(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return next((nested for arg in get_args(annotation) if (nested := _model(arg))), None)


def _field(model: type[BaseModel], name: str) -> FieldInfo | None:
    return next(
        (
            field
            for key, field in model.model_fields.items()
            if name in (key, field.alias, field.validation_alias)
        ),
        None,
    )


def _field_paths(field: FieldInfo, value: Any, key: str, *, env: bool) -> list[str]:
    nested = _model(field.annotation)
    if nested is None:
        return []
    children: Iterable[tuple[Any, Any]]
    if get_origin(field.annotation) is dict and isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:
        return unknown_paths(nested, value, key + ".", env=env)
    return [
        path
        for label, item in children
        for path in unknown_paths(nested, item, f"{key}.{label}.", env=env)
    ]


def unknown_paths(
    model: type[BaseModel], data: Any, prefix: str = "", *, env: bool = False
) -> list[str]:
    if not isinstance(data, dict):
        return []
    result = []
    for name, value in data.items():
        if not isinstance(name, str):
            continue
        name = name.lower() if env else name
        key = prefix + name
        field = _field(model, name)
        if field is not None:
            result.extend(_field_paths(field, value, key, env=env))
        elif prefix:
            # Keep strict top-level validation unchanged.
            result.append(key)
    return result


def _json_environment_keys(model: type[BaseModel], part: str, actual: str) -> list[str]:
    try:
        data = json.loads(os.environ[actual])
    except (ValueError, TypeError):
        return []  # Existing validation reports invalid JSON.
    # Walk the field itself so typed maps retain their account labels.
    paths = unknown_paths(model, {part: data}, "section.", env=True)
    suffixes = [key.removeprefix(f"section.{part}.").upper().replace(".", "__") for key in paths]
    return [f"{actual}__{suffix}" for suffix in suffixes]


def _environment_keys(model: type[BaseModel], parts: list[str], actual: str) -> list[str]:
    part = parts[0]
    field = _field(model, part)
    if field is None:
        return [actual]
    nested = _model(field.annotation)
    if len(parts) == 1:
        return _json_environment_keys(model, part, actual) if nested else []
    if get_origin(field.annotation) is dict:
        # Arbitrary provider options are valid; typed maps skip the account label.
        if nested is None or len(parts) <= 2:
            return []
        return _environment_keys(nested, parts[2:], actual)
    if nested is None:
        return [actual]
    return _environment_keys(nested, parts[1:], actual)


def unknown_environment(model: type[BaseModel]) -> list[str]:
    result = []
    for actual in os.environ:
        name = actual.upper()
        if not name.startswith("IMMICH_MEMORIES_"):
            continue
        suffix = name.removeprefix("IMMICH_MEMORIES_")
        if suffix not in _PROCESS_KEYS:
            result.extend(_environment_keys(model, suffix.lower().split("__"), actual))
    return result
