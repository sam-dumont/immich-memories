"""Session revocation generations: atomic bumps on both backends, carried forward by migration.

The counts were one JSON dict read, changed and written back, so two concurrent sign-outs
on PostgreSQL dropped one revocation; each key is now an integer row bumped by a single
INSERT .. ON CONFLICT statement. These tests run on SQLite and, when
`IMMICH_MEMORIES_TEST_DATABASE_URL` names a server, on PostgreSQL.
"""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from immich_memories.config_loader import Config
from immich_memories.db import Store, now_db, open_store, upgrade
from immich_memories.db.migrate import downgrade
from immich_memories.db.tables.session_generations import session_generations
from immich_memories.db.tables.store_meta import store_meta
from immich_memories.web.session_validity import end_sessions, session_generation

_LEGACY_KEY = "auth.session_generations"


@pytest.fixture(autouse=True)
def _store_from_this_tests_location(monkeypatch: pytest.MonkeyPatch, location):
    """The suite pins `IMMICH_MEMORIES_DATABASE_URL`, and `resolve_location` lets the
    environment outrank a passed config's own `database:` section; point both at this
    test's location so `end_sessions`' `open_store(config)` lands in the fixture store."""
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)


def _counts(store: Store) -> dict[str, int]:
    with store.connect() as connection:
        return {  # noqa: C416 — dict() would subscript the CursorResult, not iterate it
            key: generation
            for key, generation in connection.execute(
                sa.select(session_generations.c.key, session_generations.c.generation)
            )
        }


def test_concurrent_sign_outs_each_land_their_bump(store):
    config = Config()
    barrier = threading.Barrier(3)

    def sign_out_everyone():
        barrier.wait()
        end_sessions(config, None)

    threads = [threading.Thread(target=sign_out_everyone) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert _counts(store) == {"*": 2}
    assert session_generation(config, "user-one") == 2


def test_one_users_sign_out_does_not_touch_another(store):
    config = Config()

    end_sessions(config, "user-one")
    end_sessions(config, "user-two")

    assert _counts(store) == {"user-one": 1, "user-two": 1}
    assert session_generation(config, "user-one") == 1
    assert session_generation(config, "user-absent") == 0


def test_a_generation_never_goes_back(store):
    config = Config()

    end_sessions(config, "user-one")
    before = session_generation(config, "user-one")
    end_sessions(config, "user-one")

    assert session_generation(config, "user-one") == before + 1


def test_legacy_generation_counts_are_carried_forward(store):
    downgrade(store, "0012_annotation_assets_is_edited")
    with store.begin() as connection:
        connection.execute(
            sa.insert(store_meta).values(
                key=_LEGACY_KEY,
                value={"*": 2, "user-one": 3},
                updated_at=now_db(),
            )
        )

    upgrade(store)

    assert _counts(store) == {"*": 2, "user-one": 3}
    with store.connect() as connection:
        legacy = connection.execute(
            sa.select(store_meta.c.key).where(store_meta.c.key == _LEGACY_KEY)
        ).scalar()
    assert legacy is None, "the migrated rows replace the dict, so it cannot disagree with them"
    assert open_store(location=store.location) is not None


def test_concurrent_logouts_refuse_both_copied_cookies(store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

    config = basic_auth_config()
    client = server_client(monkeypatch, config)
    cookies = [signed_session(config, username=name) for name in ("user-one", "user-two")]
    barrier = threading.Barrier(2)

    def sign_out(cookie):
        headers = {"cookie": f"session={cookie}"}
        assert client.get("/api/v1/connection", headers=headers).status_code == 200
        barrier.wait(timeout=10)
        return client.post("/logout", headers=headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(sign_out, cookies)) == [303, 303]

    for cookie in cookies:
        assert (
            client.get("/api/v1/connection", headers={"cookie": f"session={cookie}"}).status_code
            == 401
        )
