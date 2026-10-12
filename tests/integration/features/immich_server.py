"""The Immich a feature test talks to: the fake one, or a real one seeded with the same library.

`make test-features` runs the suite against the fake Immich (`tests/e2e/fake_immich.py`);
`make test-features-real-immich` runs it again against a real Immich that `real_seed.py`
filled with the same files, and names its state file in ``FEATURE_IMMICH_STATE``. A test asks
for the `immich` fixture and gets either, through this one shape.

The fixture library names its pictures by readable ids. The fake serves them under those ids;
a real Immich gives each upload its own, so a test that hands an id to the CLI asks
`immich.id_of` for the server's. The scripted editor follows file names and needs no help.

A test that can only run on the fake (it forces a failure the fake injects, reads the fake's
request or upload log, or swaps what it serves) says so with
``@pytest.mark.fake_immich_only("why")``; the real pass skips it with that reason.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tests.e2e.fake_immich import FakeImmichServer

STATE_ENV = "FEATURE_IMMICH_STATE"


def real_immich_state() -> Path | None:
    """The seeded real Immich's state file this run was given, if it was given one."""
    value = os.environ.get(STATE_ENV, "")
    return Path(value) if value else None


@dataclass(frozen=True, slots=True)
class LibraryServer:
    """An Immich serving the fixture library on two accounts."""

    base_url: str
    api_key: str
    partner_api_key: str
    # The Immich major it answers as.
    major: int
    # Where the library's files were rendered (the fake serves them; the seed uploaded them).
    media: Path
    # Fixture id -> the server's id. Empty on the fake, whose ids are the fixture's.
    asset_ids: Mapping[str, str] = field(default_factory=dict)
    # The same for people ("person-robin") and albums.
    person_ids: Mapping[str, str] = field(default_factory=dict)
    album_ids: Mapping[str, str] = field(default_factory=dict)

    @property
    def real(self) -> bool:
        return bool(self.asset_ids)

    def id_of(self, fixture_id: str) -> str:
        """The id this server holds a fixture picture under."""
        return self.asset_ids[fixture_id] if self.real else fixture_id

    def ids_of(self, fixture_ids: Iterable[str]) -> list[str]:
        return [self.id_of(fixture_id) for fixture_id in fixture_ids]

    def person_of(self, fixture_id: str) -> str:
        """The id this server holds a fixture person under ("person-robin" on the fake)."""
        return self.person_ids[fixture_id] if self.real else fixture_id

    @classmethod
    def of_fake(cls, server: FakeImmichServer) -> LibraryServer:
        return cls(
            base_url=server.base_url,
            api_key=server.api_key,
            partner_api_key=server.partner_api_key,
            major=server.wire.major,
            media=server.root / "media",
        )

    @classmethod
    def of_state(cls, path: Path) -> LibraryServer:
        state = json.loads(path.read_text())
        return cls(
            base_url=state["url"],
            api_key=state["api_key"],
            partner_api_key=state["partner_api_key"],
            major=int(state["major"]),
            media=Path(state["media"]),
            asset_ids=state["asset_ids"],
            person_ids=state["person_ids"],
            album_ids=state["album_ids"],
        )
