"""Where the store lives, decided before it opens.

The URL and schema come from the environment, then `config.yaml`, then the default SQLite file.
They can never come from the store itself: nothing can be read from a database before
knowing which one it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

URL_ENV = "IMMICH_MEMORIES_DATABASE_URL"
SCHEMA_ENV = "IMMICH_MEMORIES_DATABASE_SCHEMA"
DEFAULT_URL = "sqlite:///~/.immich-memories/store.db"
DEFAULT_SCHEMA = "immich_memories"

# `postgresql://` alone would pick psycopg2, which is not installed.
_DRIVERS = {
    "sqlite": "sqlite",
    "sqlite+pysqlite": "sqlite",
    "postgres": "postgresql+psycopg",
    "postgresql": "postgresql+psycopg",
    "postgresql+psycopg": "postgresql+psycopg",
}


def redact_url(url: str | URL) -> str:
    """The URL with its password replaced by `***`, safe for logs and error messages."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except ArgumentError:
        return "<unparseable database URL>"


@dataclass(frozen=True)
class StoreLocation:
    """A normalized store URL plus the PostgreSQL schema; prints itself redacted."""

    url: str
    schema: str = DEFAULT_SCHEMA

    @property
    def sa_url(self) -> URL:
        return make_url(self.url)

    @property
    def dialect_name(self) -> str:
        return self.sa_url.get_backend_name()

    @property
    def sqlite_path(self) -> Path | None:
        """The database file, or None for PostgreSQL and in-memory SQLite.

        `normalize_url` already expands `~` for any `StoreLocation` built through
        `resolve_location`; this expands again so a `StoreLocation` built directly from a
        raw URL (a test, a future caller) can never hand back a literal `~` segment that
        a file open resolves relative to the current directory instead of home (#2009).
        """
        url = self.sa_url
        database = url.database
        if url.get_backend_name() != "sqlite" or not database or database == ":memory:":
            return None
        return Path(database).expanduser()

    def __repr__(self) -> str:
        return f"StoreLocation(url={redact_url(self.url)!r}, schema={self.schema!r})"

    def __str__(self) -> str:
        return redact_url(self.url)


def normalize_url(raw: str) -> str:
    """Pin the psycopg 3 driver and expand `~` in a SQLite path; refuse any other backend."""
    try:
        url = make_url(raw)
    except ArgumentError:
        # The raw text may hold a password; never echo it.
        raise ValueError("the store URL could not be parsed") from None
    driver = _DRIVERS.get(url.drivername)
    if driver is None:
        raise ValueError(
            f"unsupported store backend {url.drivername!r}: use sqlite:/// or postgresql://"
        )
    url = url.set(drivername=driver)
    if driver == "sqlite" and url.database and url.database != ":memory:":
        url = url.set(database=str(Path(url.database).expanduser()))
    return url.render_as_string(hide_password=False)


def _default_store_url() -> str:
    """The SQLite file beside the loaded config, so a `--config PATH` run keeps its own store.

    `DEFAULT_URL`'s literal `~/.immich-memories/store.db` is only the fallback for a bare
    `StoreLocation`, or for `resolve_location()` called with no config loaded at all (the
    module import, migration tooling). The default config path already resolves to
    `~/.immich-memories`, so a run with no `--config` lands exactly there too (#2076).
    """
    from immich_memories.config_loader import config_state_dir

    return f"sqlite:///{config_state_dir() / 'store.db'}"


def store_relocation_warning(config: Config) -> str | None:
    """Warn an upgrading `--config` user whose store moved out from under them (#2076).

    Before this fix, every `--config` run's store was `~/.immich-memories/store.db`
    regardless of which config it was. A config that never set `database.url` now gets its
    own store beside itself (`resolve_location`); without this warning, a user who already
    has history and banked facts under the old path would open what looks like an empty
    store the first time they run with the fixed version, with no sign why. Returns a
    message only in exactly that situation: no explicit `database.url`, the new and old
    paths differ, the new one does not exist yet, and the old one does.
    """
    if config.database.url not in ("", DEFAULT_URL):
        return None
    new_path = resolve_location(config).sqlite_path
    if new_path is None:
        return None
    old_path = StoreLocation(url=normalize_url(DEFAULT_URL)).sqlite_path
    if old_path is None or new_path == old_path or new_path.exists() or not old_path.exists():
        return None
    return (
        f"This config's store is now {new_path}, not the old {old_path}: existing run "
        f"history and banked facts will not show up here. Keep using the old store by adding "
        f"`database.url: sqlite:///{old_path}` to this config, or move it: "
        f"`immich-memories store backup` against the old default, then `immich-memories "
        f"--config <this config> store restore --from <the backup>` — or just copy the file "
        f"to {new_path}."
    )


def resolve_location(config: Config | None = None) -> StoreLocation:
    """The environment, then `config.yaml`'s `database:` section, then the loaded config's own file.

    Without a config the loaded one is used. `~` is expanded on every call, so a test or a
    container that moves HOME moves the default store with it. `config.database.url` still
    holding its pydantic default (never set by the user) is not treated as explicit: the
    default store instead follows the config that was loaded, not a hardcoded home path.
    """
    env_url, env_schema = os.environ.get(URL_ENV), os.environ.get(SCHEMA_ENV)
    if config is None and env_url and (env_schema or env_url.startswith("sqlite")):
        # The environment names everything the location needs: config.yaml is not read, so
        # nothing it would log or fail on comes along.
        return StoreLocation(url=normalize_url(env_url), schema=env_schema or DEFAULT_SCHEMA)
    if config is None:
        from immich_memories.config_loader import get_config

        config = get_config()
    configured_url = config.database.url
    url_from_config = (
        _default_store_url() if configured_url in ("", DEFAULT_URL) else configured_url
    )
    url = env_url or url_from_config
    schema = env_schema or config.database.schema_name or DEFAULT_SCHEMA
    return StoreLocation(url=normalize_url(url), schema=schema)
