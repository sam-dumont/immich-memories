"""Fetch the pinned model artifacts an install needs before its first cut."""

from __future__ import annotations

import urllib.error
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import click

from immich_memories.analysis.editorial_preparation_detectors import DETECTOR_SNAPSHOTS
from immich_memories.model_acquisition import acquisition_plan
from immich_memories.pinned_models import fetch_pinned_model
from immich_memories.security import sanitize_error_message


def register_models_commands(cli_group: click.Group) -> None:
    """Register the `models` group that prepares an install's pinned artifacts."""

    @cli_group.group()
    def models() -> None:
        """Fetch the pinned model artifacts selection needs."""

    @models.command()
    @click.option("--force", is_flag=True, help="Re-download even when the file is already right")
    @click.option(
        "--detectors/--no-detectors",
        default=None,
        help="Fetch detector models (default: gpu/full only); --detectors also fetches on nas",
    )
    @click.option(
        "--laya",
        is_flag=True,
        help="Fetch the Laya audience checkpoint even on the nas tier (gpu and full fetch it anyway)",
    )
    @click.pass_context
    def fetch(ctx: click.Context, force: bool, detectors: bool | None, laya: bool) -> None:
        """Download every pinned model artifact a first cut needs, in one command."""
        config = ctx.obj["config"]
        preparation = config.editorial.preparation
        plan = acquisition_plan(config, detectors=detectors, laya=laya)
        if detectors is None:
            detectors = config.editorial.detectors_enabled
        total = len(plan) + int(detectors)
        for index, item in enumerate(plan, 1):
            click.echo(f"models: {index}/{total} {item.cli_label or item.artifact.label}")
            _fetch_pinned(
                label=item.cli_label or item.artifact.label,
                url=item.url,
                destination=item.destination,
                sha256=item.artifact.sha256,
                force=force,
                max_bytes=item.max_bytes,
            )
        if not detectors:
            return
        click.echo(f"models: {total}/{total} detector snapshots")
        try:
            for repo in warm_detectors(preparation.detector_cache_dir):
                click.echo(f"detector: cached {repo}")
        except (ImportError, OSError, ValueError) as exc:
            click.echo(f"detectors: {exc}")
            raise SystemExit(1) from exc


def _fetch_pinned(
    *,
    label: str,
    url: str,
    destination: Path,
    sha256: str,
    force: bool,
    max_bytes: int | None = None,
) -> None:
    limit = {} if max_bytes is None else {"max_bytes": max_bytes}
    try:
        outcome = fetch_pinned_model(
            url=url, destination=destination, sha256=sha256, force=force, **limit
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        click.echo(f"{label}: {_safe_download_error(exc, url)}")
        raise SystemExit(1) from exc
    verb = "already present at" if outcome == "present" else "downloaded to"
    click.echo(f"{label}: {verb} {destination}")


def warm_detectors(cache_dir: str) -> list[str]:
    """Pull every pinned Hugging Face detector file into the cache the worker reads offline.

    Returns one ``repo@revision`` label per warmed snapshot. The worker runs with
    ``HF_HUB_OFFLINE=1`` unless `allow_model_downloads` is on, so this is what
    makes that default honest on a cold install.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise ImportError(
            "the detectors need the editorial extra: pip install 'immich-memories[editorial]'"
        ) from exc

    resolved = str(Path(cache_dir).expanduser()) if cache_dir.strip() else None
    warmed = []
    for repo, revision, filenames in DETECTOR_SNAPSHOTS:
        for filename in filenames:
            hf_hub_download(repo, filename, revision=revision, cache_dir=resolved)
        warmed.append(f"{repo}@{revision[:8]}")
    return warmed


def _safe_download_error(error: Exception, url: str) -> str:
    """A mirror URL may hold credentials outside the ordinary configured secret fields."""
    message = str(error).replace(url, "model source")
    try:
        parsed = urlsplit(url)
    except ValueError:
        return sanitize_error_message(message)
    secrets = {unquote(value) for value in (parsed.username, parsed.password) if value}
    secrets.update(value for _, value in parse_qsl(parsed.query) if value)
    for secret in sorted(secrets, key=len, reverse=True):
        message = message.replace(secret, "***")
    return sanitize_error_message(message)
