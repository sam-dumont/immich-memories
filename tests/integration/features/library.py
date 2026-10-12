"""The fixture library as the feature tests use it: which days to film and what each keeps."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import ALL_PICTURES, CARRIERS, DROPPED
from tests.features.cli_harness import RUN_ID, CliResult, UserHome, films_under

# The first day away: the clip at Møns Klint and two stills ship (the cliffs, and Charlie
# on the bike in Copenhagen, a person and a place), everything else that day is left out.
DEPARTURE_DAY = "2025-07-12"
# A day with a single still that ships: the cheapest film the library makes.
QUIET_DAY = "2025-07-02"


def day_args(day: str) -> tuple[str, ...]:
    return ("generate", "--start", day, "--end", day, "--include-photos", "--no-music", "--quiet")


def shipped_on(day: str) -> list:
    """The pictures the scripted editor keeps from one day, in capture order."""
    return sorted((p for p in CARRIERS if p.day == day), key=lambda p: (p.taken_at, p.asset_id))


def left_out_on(day: str) -> list[str]:
    """The ids the scripted editor leaves out of one day."""
    return sorted(p.asset_id for p in ALL_PICTURES if p.asset_id in DROPPED and p.day == day)


@dataclass(frozen=True, slots=True)
class RenderedRun:
    """A finished `generate`: what it printed, the film it wrote and the run it recorded."""

    result: CliResult
    film: Path

    @property
    def run_id(self) -> str:
        match = RUN_ID.search(self.film.parent.name)
        assert match, self.film
        return match.group(0)


def render(home: UserHome, *args: str, into: Path | None = None) -> RenderedRun:
    """Run `generate` and return the one film it added under `into` (default ~/Videos)."""
    directory = into or home.videos
    before = set(films_under(directory)) if directory.exists() else set()
    result = home.run(*args, scripted_selection=True)
    assert result.returncode == 0, result.explain()
    added = [film for film in films_under(directory) if film not in before]
    assert len(added) == 1, f"expected one new film, got {added}\n{result.explain()}"
    return RenderedRun(result, added[0])


@contextmanager
def own_immich(root: Path, library: FakeImmichServer) -> Iterator[FakeImmichServer]:
    """A fake Immich serving the session's library with no upload, tag or album change yet.

    A test that asserts on what reached Immich (the uploads, their ids, their tags) runs
    against one of these, so what other tests on the same worker uploaded cannot change it.
    """
    server = FakeImmichServer.start(root, media_of=library)
    try:
        yield server
    finally:
        server.close()
    # As for the session's service: a request the real Immich would refuse fails the test.
    assert server.refused == [], server.refused
