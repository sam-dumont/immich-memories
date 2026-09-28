"""Capture the vocabulary needed to redact this run without querying Immich to report it."""

from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from immich_memories import __version__
from immich_memories.logging_config import install_secret_redaction
from immich_memories.security import configured_secret_values
from immich_memories.tracking.timing import active


def private_place_name(resolve):
    """Remember resolved and cached geocoder labels before they can appear in a report."""

    @wraps(resolve)
    def record(*args, **kwargs):
        name = resolve(*args, **kwargs)
        collected = active()
        if name and collected is not None:
            collected.private_terms.add(name)
            collected.private_terms.update(part.strip() for part in name.split(",") if part.strip())
        return name

    return record


def install_method() -> str:
    """Prefer explicit container evidence over editable-package guesses."""
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "Kubernetes"
    if Path("/.dockerenv").exists():
        return "Docker"
    if (Path(__file__).resolve().parents[3] / ".git").exists():
        return "source"
    return "pip"


def record_config(config, arguments: dict) -> None:
    """Keep config shape and a private redaction vocabulary, never a config dump."""
    collected = active()
    if collected is None:
        return
    install_secret_redaction(configured_secret_values(config))
    collected.private_terms.update(
        str(path)
        for path in (
            Path.home(),
            config.output.output_path,
            config.cache.cache_path,
        )
    )
    for key in ("person", "album", "title", "subtitle", "output", "from_album", "subject"):
        value = arguments.get(key)
        if isinstance(value, (str, Path)):
            collected.private_terms.add(str(value))
        elif isinstance(value, (tuple, list)):
            collected.private_terms.update(str(item) for item in value)
    collected.diagnostics.update(
        version=__version__,
        install_method=install_method(),
        tier=config.tier,
        config_shape={
            "llm": "configured" if config.llm.model else "not configured",
            "location": "local"
            if urlsplit(config.llm.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
            else "hosted",
            "protocol": config.llm.provider,
        },
    )


def record_assets(assets) -> None:
    """Retain IDs and personal labels only for redaction; no pixels or captions."""
    collected = active()
    if collected is None:
        return
    for source in assets:
        asset = getattr(source, "asset", source)
        collected.private_ids.update([asset.id, *(person.id for person in asset.people)])
        collected.private_terms.update(filter(None, _asset_labels(asset)))


def _asset_labels(asset):
    yield asset.original_path
    yield asset.original_file_name
    yield from (person.name for person in asset.people)
    if asset.exif_info:
        yield from (asset.exif_info.city, asset.exif_info.state, asset.exif_info.country)
