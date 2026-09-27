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
        """The database file, or None for PostgreSQL and in-memory SQLite."""
        url = self.sa_url
        database = url.database
        if url.get_backend_name() != "sqlite" or not database or database == ":memory:":
            return None
        return Path(database)

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


def resolve_location(config: Config | None = None) -> StoreLocation:
    """The environment, then `config.yaml`'s `database:` section, then the default SQLite file.

    Without a config the loaded one is used. `~` is expanded on every call, so a test or a
    container that moves HOME moves the default store with it.
    """
    env_url, env_schema = os.environ.get(URL_ENV), os.environ.get(SCHEMA_ENV)
    if config is None and env_url and (env_schema or env_url.startswith("sqlite")):
        # The environment names everything the location needs: config.yaml is not read, so
        # nothing it would log or fail on comes along.
        return StoreLocation(url=normalize_url(env_url), schema=env_schema or DEFAULT_SCHEMA)
    if config is None:
        from immich_memories.config_loader import get_config

        config = get_config()
    url = env_url or config.database.url or DEFAULT_URL
    schema = env_schema or config.database.schema_name or DEFAULT_SCHEMA
    return StoreLocation(url=normalize_url(url), schema=schema)
