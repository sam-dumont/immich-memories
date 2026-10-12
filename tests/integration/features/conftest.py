"""Feature tests on the CC0 fixture library, rendered with real FFmpeg (`make test-features`).

One Immich serves the fixture library over HTTP for the whole session, and one sealed home
holds a Basic install pointed at it. By default it is the fake Immich the launch check uses;
`make test-features-real-immich` runs the same tests against a real Immich seeded with the
same files (`immich_server.py`, `real_seed.py`). Tests take `immich` for either; a test that
needs the fake itself takes `fake_immich` and carries `fake_immich_only` with its reason.
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
from tests.integration.features.immich_server import LibraryServer, real_immich_state
from tests.integration.features.library import (
    GARDEN_DAY,
    RenderedRun,
    day_args,
    own_immich,
    render,
)

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, with its reason, what the Immich this run talks to cannot drive."""
    real = real_immich_state() is not None
    for item in items:
        if not item.path.is_relative_to(_HERE):
            continue
        fake_only = item.get_closest_marker("fake_immich_only")
        if real and fake_only is not None:
            reason = fake_only.args[0] if fake_only.args else "needs the fake Immich"
            item.add_marker(pytest.mark.skip(reason=f"fake Immich only: {reason}"))
        elif not real and item.get_closest_marker("real_immich_only") is not None:
            item.add_marker(
                pytest.mark.skip(reason="needs a real Immich: make test-features-real-immich")
            )


@pytest.fixture(scope="session")
def immich(request: pytest.FixtureRequest) -> LibraryServer:
    """The Immich serving the fixture library: the fake, or the seeded real one."""
    state = real_immich_state()
    if state is not None:
        return LibraryServer.of_state(state)
    return LibraryServer.of_fake(request.getfixturevalue("fake_immich"))


@pytest.fixture(scope="session")
def fake_immich(tmp_path_factory: pytest.TempPathFactory) -> Generator[FakeImmichServer]:
    if real_immich_state() is not None:
        pytest.fail(
            "this test drives the fake Immich on a real-Immich run: take `immich` instead, "
            "or mark it fake_immich_only with the reason"
        )
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
    immich: LibraryServer,
    outbound_trap: OutboundTrap,
) -> UserHome:
    """A Basic install whose config, store, logs and films all live in one throwaway home.

    Every command it runs goes through `outbound_trap`: anything that tries to leave the
    machine other than the configured Immich is recorded there.
    """
    home = UserHome(
        tmp_path_factory.mktemp("feature-home"), extra_env=tuple(outbound_trap.env().items())
    )
    home.write_config(basic_config(immich.base_url, immich.api_key, home))
    return home


@pytest.fixture
def fresh_home(tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap) -> UserHome:
    """A Basic install of this test's own, on the session's library, with no run history.

    For a test whose answer depends on the history (what a prefix matches, what is left
    to propose): `library_home` holds whatever the tests before it on this worker made.
    """
    home = UserHome(tmp_path / "fresh-home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(immich.base_url, immich.api_key, home))
    return home


@pytest.fixture(scope="session")
def garden_film(library_home: UserHome) -> RenderedRun:
    """One fixture day rendered with every default, named with --output."""
    return render(
        library_home, *day_args(GARDEN_DAY), "--output", str(library_home.videos / "garden.mp4")
    )
