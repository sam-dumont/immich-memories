"""Is a newer release out? One anonymous request, compared with the running version here.

The only outside call this module makes is an unauthenticated GET of the public GitHub
releases list. Nothing about this install goes with it: no version, no install id, no
setting, and a user agent that is just the project name. The running version is compared
with the answer locally, so what the repository learns is that somebody asked.

Releases are not `releases/latest`: that points at whichever release was published last,
asset releases (`music-v3`, `models-v2`) and the rolling `nightly` included. The list is
filtered to this app's own version tags and the highest one for the install's channel wins.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx
import sqlalchemy as sa
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel

from immich_memories import __version__
from immich_memories.config.models.updates import RELEASES_HOST
from immich_memories.db import now_db, open_store, upsert
from immich_memories.db.tables.store_meta import store_meta
from immich_memories.laya_checkpoints import LAYA_MLX_REQUIREMENT
from immich_memories.preflight_output import running_in_container

if TYPE_CHECKING:
    from immich_memories.config.loader import Config

logger = logging.getLogger(__name__)

REPOSITORY = "sam-dumont/immich-memories"
RELEASES_URL = f"https://{RELEASES_HOST}/repos/{REPOSITORY}/releases"
NOTES_URL = f"https://github.com/{REPOSITORY}/releases/tag"
IMAGE = f"ghcr.io/{REPOSITORY}"
DOCS_URL = "https://sam-dumont.github.io/immich-memories/docs/run/maintenance/upgrading"
# A fixed word on purpose: a version here would tell the repository what is running.
USER_AGENT = "immich-memories"

CACHE_KEY = "update_check"
CHECK_EVERY = timedelta(days=1)

# The app's own tags: v1.0.0 and v1.0.0-rc.N. Asset releases and `nightly` do not match.
_APP_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")

InstallMethod = Literal["docker", "kubernetes", "pip", "unknown"]


class UpdateCheckFailed(Exception):
    """GitHub could not be asked or answered unreadably; the message says why, plainly."""


class UpdateStatus(BaseModel):
    """What a check found: a release to install, nothing newer, or why it could not tell."""

    status: Literal["available", "current", "failed"]
    running: str
    latest: str | None = None
    notes_url: str | None = None
    command: str | None = None
    install_method: InstallMethod = "unknown"
    docs_url: str = DOCS_URL
    reason: str | None = None


def release_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The client the check uses: a plain user agent, no credentials, a short timeout."""
    return httpx.Client(
        transport=transport,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        timeout=10.0,
        follow_redirects=True,
    )


def _version_of(tag: str) -> Version | None:
    match = _APP_TAG.match(tag)
    if not match:
        return None
    major, minor, patch, candidate = match.groups()
    return Version(f"{major}.{minor}.{patch}" + (f"rc{candidate}" if candidate else ""))


def fetch_release_tags(client: httpx.Client) -> list[str]:
    """The app's published (not draft) version tags, as GitHub lists them."""
    try:
        response = client.get(RELEASES_URL, params={"per_page": 100})
    except httpx.TimeoutException as error:
        raise UpdateCheckFailed("could not reach GitHub: the request timed out") from error
    except httpx.HTTPError as error:
        # The error text can name hosts or proxies; the kind of failure is enough.
        raise UpdateCheckFailed(
            f"could not reach GitHub ({type(error).__name__}); check the network"
        ) from error
    if response.status_code != 200:
        raise UpdateCheckFailed(f"GitHub answered {response.status_code} to the release list")
    try:
        releases = response.json()
    except ValueError as error:
        raise UpdateCheckFailed("GitHub's answer was not a release list") from error
    if not isinstance(releases, list):
        raise UpdateCheckFailed("GitHub's answer was not a release list")
    return [
        tag
        for release in releases
        if isinstance(release, dict)
        and not release.get("draft")
        and isinstance(tag := release.get("tag_name"), str)
        and _version_of(tag) is not None
    ]


def newest_offered(tags: list[str], running: Version) -> str | None:
    """The highest tag newer than `running` that its channel is offered, or None.

    A stable install is offered stable releases. A release candidate is offered newer
    candidates and stable releases. A nightly (a dev build) is offered the next stable
    release, never a candidate.
    """
    stable_only = running.is_devrelease or not running.is_prerelease
    offered = [
        (version, tag)
        for tag in tags
        if (version := _version_of(tag)) is not None
        and version > running
        and not (stable_only and version.is_prerelease)
    ]
    return max(offered)[1] if offered else None


def detect_install_method(
    *,
    env: Mapping[str, str] = os.environ,
    exists: Callable[[str], bool] = os.path.exists,
    in_source_tree: bool | None = None,
) -> InstallMethod:
    """How this copy was installed, from container evidence the app already trusts.

    A source checkout (or anything this cannot tell) is "unknown", which links the
    upgrading docs rather than guessing a command.
    """
    if env.get("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    if running_in_container(exists, env):
        return "docker"
    if in_source_tree is None:
        in_source_tree = (Path(__file__).resolve().parents[2] / ".git").exists()
    return "unknown" if in_source_tree else "pip"


def installed_via() -> InstallMethod:
    """`detect_install_method` for the running process."""
    return detect_install_method()


def update_command(method: str, tag: str, *, platform: str = sys.platform) -> str | None:
    """The command (or instruction) that installs `tag` for this install method."""
    version = tag.removeprefix("v")
    if method == "docker":
        return "docker compose pull && docker compose up -d"
    if method == "kubernetes":
        return f"Set the image to {IMAGE}:{version} and apply it"
    if method == "pip":
        mac = ("all-mac", f' --with "{LAYA_MLX_REQUIREMENT}"')
        extras, more = mac if platform == "darwin" else ("all", "")
        python = version.replace("-rc.", "rc")
        return (
            "uv tool install --python 3.12 --prerelease if-necessary-or-explicit "
            f'"immich-memories[{extras}]=={python}"{more}'
        )
    return None


def _status_for(tags: list[str], running: str, method: InstallMethod) -> UpdateStatus:
    try:
        current = Version(running)
    except InvalidVersion:
        return UpdateStatus(
            status="failed",
            running=running,
            install_method=method,
            reason="could not read the running version",
        )
    tag = newest_offered(tags, current)
    if tag is None:
        return UpdateStatus(status="current", running=running, install_method=method)
    return UpdateStatus(
        status="available",
        running=running,
        latest=tag.removeprefix("v"),
        notes_url=f"{NOTES_URL}/{tag}",
        command=update_command(method, tag),
        install_method=method,
    )


def check_for_update(running: str, method: InstallMethod, client: httpx.Client) -> UpdateStatus:
    """Ask GitHub now and compare with `running`. Never raises: a failure is a status."""
    try:
        tags = fetch_release_tags(client)
    except UpdateCheckFailed as error:
        return UpdateStatus(
            status="failed",
            running=running,
            install_method=method,
            reason=str(error),
        )
    return _status_for(tags, running, method)


def check_now() -> UpdateStatus:
    """The check behind the button and `version --check`, for the running install."""
    with release_client() as client:
        return check_for_update(__version__, installed_via(), client)


def _cached(config: Config) -> dict[str, Any] | None:
    with open_store(config).connect() as connection:
        value = connection.execute(
            sa.select(store_meta.c.value).where(store_meta.c.key == CACHE_KEY)
        ).scalar()
    return value if isinstance(value, dict) else None


def _remember(config: Config, checked_at: datetime, tags: list[str] | None) -> None:
    record = {"checked_at": checked_at.isoformat(), "tags": tags}
    with open_store(config).begin() as connection:
        upsert(
            connection,
            store_meta,
            [{"key": CACHE_KEY, "value": record, "updated_at": now_db()}],
            ["key"],
        )


def _due(record: dict[str, Any] | None, now: datetime) -> bool:
    if record is None:
        return True
    try:
        return now - datetime.fromisoformat(record["checked_at"]) >= CHECK_EVERY
    except (KeyError, TypeError, ValueError):
        return True


def daily_update_status(
    config: Config,
    running: str | None = None,
    client: httpx.Client | None = None,
    *,
    now: datetime | None = None,
) -> UpdateStatus | None:
    """The cached answer of the daily check, asking GitHub only when a day has passed.

    None when `updates.check_daily` is off (nothing goes out), or when the last attempt
    failed: a banner is for news, and a failed day is not retried until the next one.
    The cache holds the release tags, not the verdict, so an upgrade changes the answer
    without a new request.
    """
    if not config.updates.check_daily:
        return None
    now = now or datetime.now(UTC)
    running = running or __version__
    record = _cached(config)
    if _due(record, now):
        try:
            if client is None:
                with release_client() as own:
                    tags: list[str] | None = fetch_release_tags(own)
            else:
                tags = fetch_release_tags(client)
        except UpdateCheckFailed as error:
            logger.info("Update check skipped: %s", error)
            tags = None
        _remember(config, now, tags)
    else:
        tags = record["tags"] if record else None
    if tags is None:
        return None
    return _status_for(tags, running, installed_via())


def log_daily_update_notice(config: Config) -> None:
    """One line in the run log when the daily check knows of a newer release.

    A run never fails or waits long because of this: the store being unreadable is
    the only thing besides GitHub it depends on, and both end as a skipped line.
    """
    try:
        status = daily_update_status(config)
    except sa.exc.SQLAlchemyError:
        logger.debug("Update check skipped: the store could not be read", exc_info=True)
        return
    if status is not None and status.status == "available":
        logger.info("Immich Memories %s is out: %s", status.latest, status.notes_url)
