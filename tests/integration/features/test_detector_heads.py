"""What the detector heads read reaches the film (#2483).

The other real-editor films prepare at `metadata_only` and run no head at all. Here `generate`
keeps Basic's own preparation, with the producers that need the pinned ONNX exports answering
from the fixture library (`scripted_preparation.py`): the real preparation decides which
pictures owe which head, the scripted producer banks the rows, and the audience check, the
editor and the render read them back from the store as they would on a user's machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import ALL_PICTURES, LIVE_DAY
from tests.features.cli_harness import OutboundTrap, UserHome
from tests.integration.features.real_editor import EditedFilm, generate, home_on
from tests.integration.features.scripted_preparation import run_prepared

pytestmark = pytest.mark.fake_immich_only("the scripted heads answer by fixture id")

_BIRTHDAY = "2025-07-05"
# One picture of the party the exposure head reads as somebody uncovered (a false positive, as
# the owner prefers to a miss); every other head and picture reads clean.
_FLAGGED = "birthday-stairs"


@pytest.fixture
def home(tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap) -> UserHome:
    return home_on(tmp_path / "home", fake_immich, outbound_trap.env())


def _day(
    home: UserHome, day: str, sharing: str, log: Path, heads: dict | None = None
) -> EditedFilm:
    return generate(
        home,
        *("--start", day, "--end", day, "--include-photos", "--no-music", "--quiet"),
        *("--sharing", sharing),
        runner=lambda h, *args: run_prepared(h, *args, heads=heads, log=str(log)),
    )


def _asked(log: Path) -> dict[str, set[str]]:
    """Which ids each scripted producer was asked to read, over every run that logged here."""
    asked: dict[str, set[str]] = {}
    for line in log.read_text().splitlines():
        entry = json.loads(line)
        asked.setdefault(entry["producer"], set()).update(entry["ids"])
    return asked


@pytest.mark.feature("sharing.levels")
def test_a_picture_the_exposure_head_flags_stays_in_the_family_film_only(
    home: UserHome, tmp_path: Path
):
    log = tmp_path / "producers.jsonl"
    flagged = {_FLAGGED: {"uncovered_person": "yes"}}

    family = _day(home, _BIRTHDAY, "family", log, flagged)
    shared = _day(home, _BIRTHDAY, "shareable", log, flagged)

    day = {p.asset_id for p in ALL_PICTURES if p.day == _BIRTHDAY}
    # The real preparation demanded the heads of exactly the day's pictures, once: the second
    # film read them back from the store.
    assert _asked(log)["public_heads"] == day
    assert _FLAGGED in {row["asset_id"] for row in family.carriers}
    kept = {row["asset_id"] for row in shared.carriers}
    assert _FLAGGED not in kept
    assert kept == {row["asset_id"] for row in family.carriers} - {_FLAGGED}
    verdict = shared.plan["shareability"]["verdicts"][_FLAGGED]
    assert (verdict["verdict"], verdict["finding"]) == ("family_only", "exposure_evidence")


@pytest.mark.xfail(
    strict=True,
    reason="needs a product ruling: Basic reads no Live Photo clip, yet a shareable film plays "
    "the unread clip as motion (clean_evidence skips a companion with no reading)",
)
def test_a_shareable_film_plays_no_live_clip_that_no_detector_read(home: UserHome, tmp_path: Path):
    """`clean_evidence`: an unread member or Live clip keeps its unit in the family."""
    log = tmp_path / "producers.jsonl"

    shared = _day(home, LIVE_DAY, "shareable", log)

    read = set().union(
        *(ids for producer, ids in _asked(log).items() if producer != "public_heads")
    )
    playing = {clip for row in shared.carriers for clip in row.get("video_ids") or ()}
    assert playing, shared.carriers
    assert playing <= read, sorted(playing - read)
