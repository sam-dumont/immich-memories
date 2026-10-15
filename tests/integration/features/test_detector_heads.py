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


def test_a_shareable_film_plays_no_live_clip_that_no_detector_read(home: UserHome, tmp_path: Path):
    """An unread Live clip keeps its picture in the shared film, as its still (#2563)."""
    log = tmp_path / "producers.jsonl"

    family = _day(home, LIVE_DAY, "family", log)
    shared = _day(home, LIVE_DAY, "shareable", log)

    read = set().union(
        *(ids for producer, ids in _asked(log).items() if producer != "public_heads")
    )
    playing = {
        clip
        for row in shared.carriers
        if row["kind"] == "live-motion"
        for clip in row.get("video_ids") or ()
    }
    assert playing <= read, sorted(playing - read)
    # Nothing is held out: every Live Photo of the family film is still in the shared one,
    # and the family film keeps the motion the shared one gave up.
    lives = {row["asset_id"] for row in family.carriers if row["kind"].startswith("live")}
    assert lives, family.carriers
    assert lives <= {row["asset_id"] for row in shared.carriers}
    assert any(row["kind"] == "live-motion" for row in family.carriers), family.carriers


@pytest.mark.feature("live-photos.motion")
def test_a_live_photo_reads_its_people_off_its_still(home: UserHome, tmp_path: Path):
    """Immich puts faces on a Live Photo's still, never on its clip, so the people head is read
    on the still alone: no clip owes it, and the Live Photo's shot carries the still's answer."""
    log = tmp_path / "producers.jsonl"
    # The still reads as a crowd, which the fixture's faces alone would never give.
    family = _day(home, LIVE_DAY, "family", log, {"live-fountain": {"people": "crowd"}})

    clips = {p.live_video_id for p in ALL_PICTURES if p.day == LIVE_DAY and p.live_video_id}
    assert clips
    assert not clips & _asked(log)["public_heads"]
    fountain = next(row for row in family.carriers if row["asset_id"] == "live-fountain")
    assert fountain["kind"].startswith("live"), fountain
    assert "people=crowd" in fountain["line"], fountain["line"]
