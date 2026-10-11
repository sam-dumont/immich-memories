"""Feature tests on the CC0 fixture library, rendered with real FFmpeg (`make test-features`).

One fake Immich serves the fixture library over HTTP for the whole session (the same
service the launch check uses), and one sealed home holds a Basic install pointed at it.
Films are rendered once and shared: `garden_film` is the default render of one fixture
day, and every test that only reads a finished run reads that one.

Selection is the hermetic launch check's scripted editor (`tests/e2e/fake_editorial.py`):
it keeps the pictures the fixture library hangs on a story. Everything a flag changes
after selection (timing, canvas, scaling, naming, the run record, the report) is real.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.features.cli_harness import OutboundTrap, UserHome, basic_config
from tests.integration.features.library import (
    GARDEN_DAY,
    RenderedRun,
    day_args,
    own_immich,
    render,
)


@pytest.fixture(scope="session")
def fake_immich(tmp_path_factory: pytest.TempPathFactory) -> Generator[FakeImmichServer]:
    server = FakeImmichServer.start(tmp_path_factory.mktemp("fake-immich"))
    yield server
    server.close()
    # A request the real Immich would refuse was answered 400 here; whatever the CLI did
    # with that answer, the session fails on it.
    assert server.refused == [], server.refused


@pytest.fixture
def delivery_immich(
    tmp_path_factory: pytest.TempPathFactory, fake_immich: FakeImmichServer
) -> Generator[FakeImmichServer]:
    """This test's own fake Immich: the same library, and only this test's uploads and tags."""
    with own_immich(tmp_path_factory.mktemp("delivery-immich"), fake_immich) as server:
        yield server


@pytest.fixture(scope="session")
def outbound_trap() -> Generator[OutboundTrap]:
    trap = OutboundTrap()
    yield trap
    trap.close()


@pytest.fixture(scope="session")
def library_home(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich: FakeImmichServer,
    outbound_trap: OutboundTrap,
) -> UserHome:
    """A Basic install whose config, store, logs and films all live in one throwaway home.

    Every command it runs goes through `outbound_trap`: anything that tries to leave the
    machine other than the configured Immich is recorded there.
    """
    home = UserHome(
        tmp_path_factory.mktemp("feature-home"), extra_env=tuple(outbound_trap.env().items())
    )
    home.write_config(basic_config(fake_immich.base_url, fake_immich.api_key, home))
    return home


@pytest.fixture
def fresh_home(
    tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap
) -> UserHome:
    """A Basic install of this test's own, on the session's library, with no run history.

    For a test whose answer depends on the history (what a prefix matches, what is left
    to propose): `library_home` holds whatever the tests before it on this worker made.
    """
    home = UserHome(tmp_path / "fresh-home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(fake_immich.base_url, fake_immich.api_key, home))
    return home


@pytest.fixture(scope="session")
def garden_film(library_home: UserHome) -> RenderedRun:
    """One fixture day rendered with every default, named with --output."""
    return render(
        library_home, *day_args(GARDEN_DAY), "--output", str(library_home.videos / "garden.mp4")
    )
