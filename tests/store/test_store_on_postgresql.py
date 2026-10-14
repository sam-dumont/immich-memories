"""The store on each backend a self-hoster can pick, driven through the real CLI.

SQLite is the default: an install that names no database keeps its store in one file under
`~/.immich-memories`. PostgreSQL is either a database of its own or a schema in Immich's
database, beside tables the app never touches, and `store copy` moves a store between the
two backends and back. The PostgreSQL cases need a server (`make test-store` starts one;
CI's store job names its service in IMMICH_MEMORIES_TEST_DATABASE_URL) and skip without one.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.features.cli_harness import UserHome, basic_config

from .backends import drop_schema, pg_url, requires_postgres
from .legacy_home import write_legacy_home

UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS
# The run the legacy home holds (legacy_home.py): what the store has in it once imported.
_LEGACY_RUN = "20240301_080000_ab12"


@pytest.fixture
def home(tmp_path: Path) -> UserHome:
    home = UserHome(tmp_path / "home")
    home.write_config(basic_config(UNREACHABLE, "a-key", home))
    return home


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """An older install's files: a run history and a people registry to fill a store with."""
    return write_legacy_home(tmp_path / "old" / "immich-memories")


def _on(url: str, schema: str | None = None) -> dict[str, str]:
    env = {"IMMICH_MEMORIES_DATABASE_URL": url}
    if schema:
        env["IMMICH_MEMORIES_DATABASE_SCHEMA"] = schema
    return env


def _filled(home: UserHome, legacy: Path, env: dict[str, str] | None = None) -> str:
    """Import the older install into the store `env` names; the history it then lists."""
    imported = home.run("store", "import", "--from", str(legacy), env=env)
    assert imported.returncode == 0, imported.explain()
    return _runs(home, env)


def _runs(home: UserHome, env: dict[str, str] | None = None) -> str:
    listed = home.run("runs", "list", "--limit", "200", env=env)
    assert listed.returncode == 0, listed.explain()
    assert _LEGACY_RUN in listed.stdout, listed.explain()
    return listed.stdout


def _status(home: UserHome, env: dict[str, str] | None = None) -> str:
    status = home.run("store", "status", env=env)
    assert status.returncode == 0, status.explain()
    return status.stdout


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"feature_{uuid.uuid4().hex[:12]}"
    yield name
    drop_schema(pg_url(), name)


@pytest.mark.feature("store.postgresql")
def test_without_a_database_setting_the_store_is_one_sqlite_file_in_the_home(
    home: UserHome, legacy: Path
):
    _filled(home, legacy)

    status = _status(home)

    assert re.search(r"Backend:\s+sqlite", status), status
    assert (home.root / ".immich-memories" / "store.db").is_file()
    assert str(home.root / ".immich-memories" / "store.db") in status


@pytest.mark.feature("store.postgresql")
@requires_postgres
def test_a_schema_in_immich_s_database_keeps_the_store_beside_immich_s_tables(
    home: UserHome, legacy: Path, schema: str
):
    url = pg_url()
    # Immich's own tables live in `public`; one stands in for them here.
    immich = sa.Table(
        f"asset_{uuid.uuid4().hex[:8]}", sa.MetaData(), sa.Column("id", sa.Text), schema="public"
    )
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            immich.create(connection)
            connection.execute(immich.insert().values(id="a-1"))
        public_before = sa.inspect(engine).get_table_names(schema="public")

        _filled(home, legacy, _on(url, schema))
        status = _status(home, _on(url, schema))

        engine.dispose()
        public_after = sa.inspect(engine).get_table_names(schema="public")
        store_tables = sa.inspect(engine).get_table_names(schema=schema)
        with engine.connect() as connection:
            immich_rows = connection.execute(sa.select(immich.c.id)).all()
    finally:
        with engine.begin() as connection:
            immich.drop(connection, checkfirst=True)
        engine.dispose()

    assert re.search(r"Backend:\s+postgresql", status), status
    assert schema in status
    assert "(at head)" in status
    password = sa.engine.make_url(url).password
    assert not password or str(password) not in status  # the password never prints
    assert {"pipeline_runs", "people_registry", "alembic_version"} <= set(store_tables)
    # Nothing landed in Immich's schema, and its rows are as they were.
    assert public_after == public_before
    assert immich_rows == [("a-1",)]


@pytest.mark.feature("store.postgresql")
@requires_postgres
def test_a_database_of_its_own_holds_the_store(home: UserHome, legacy: Path):
    server = sa.engine.make_url(pg_url())
    database = f"feature_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
    own = server.set(database=database).render_as_string(hide_password=False)
    try:
        _filled(home, legacy, _on(own))
        status = _status(home, _on(own))
    finally:
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()

    assert re.search(r"Backend:\s+postgresql", status), status
    assert database in status
    assert "(at head)" in status


@pytest.mark.feature("store.copy")
@requires_postgres
def test_store_copy_moves_a_sqlite_store_to_postgresql_and_back(
    home: UserHome, legacy: Path, schema: str, tmp_path: Path
):
    url = pg_url()
    history = _filled(home, legacy)
    back = tmp_path / "back" / "store.db"
    back.parent.mkdir()

    to_postgresql = home.run("store", "copy", "--to", url, "--schema", schema)
    on_postgresql = _runs(home, _on(url, schema))
    refused = home.run("store", "copy", "--to", url, "--schema", schema)
    forced = home.run("store", "copy", "--to", url, "--schema", schema, "--force")
    to_sqlite = home.run("store", "copy", "--to", f"sqlite:///{back}", env=_on(url, schema))
    on_sqlite_again = _runs(home, _on(f"sqlite:///{back}"))

    for copied in (to_postgresql, forced, to_sqlite):
        assert copied.returncode == 0, copied.explain()
        assert "every table matches" in " ".join(copied.stdout.split()), copied.explain()
    assert refused.returncode == 1, refused.explain()
    assert "--force" in refused.output
    # The app answers the same on each store.
    assert on_postgresql == history
    assert on_sqlite_again == history
