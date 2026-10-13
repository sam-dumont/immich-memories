"""A recorded real run replays as the cut it made, with the reasons it gave.

Each memory type was cut once for real over the fixture library (`scripts/record_demo_runs.py`)
and its decisions kept under `tests/e2e/fixtures/recordings/`. The docs and demos replay them
through the hermetic editor instead of running a model again, so the replay must be the
recorded cut: the same pictures in the same order, each held as long, and every picture left
out for the reason the real run wrote.
"""

from __future__ import annotations

import json

import pytest

from tests.e2e.fake_editorial import RECORDING_ENV, RECORDINGS
from tests.e2e.fake_library import ACCOUNTS_BY_ID
from tests.features.cli_harness import UserHome
from tests.integration.features.cuts import _SHOT, cut

pytestmark = [pytest.mark.integration, pytest.mark.fake_immich_only("replays fixture ids")]

_MONTH = ("generate", "--start", "2025-07-01", "--end", "2025-07-31", "--no-music")


def _recorded(name: str) -> dict:
    folder = RECORDINGS / name
    return {path.stem: json.loads(path.read_text()) for path in folder.glob("*.json")}


def test_a_recorded_month_replays_its_own_cut(library_home: UserHome) -> None:
    recorded = _recorded("monthly_highlights")
    projection = recorded["render-projection"]

    replay = cut(library_home, *_MONTH, env={RECORDING_ENV: "monthly_highlights"})

    picked = [ACCOUNTS_BY_ID[asset_id] for asset_id in projection["selected_ids"]]
    assert [(shot.day, shot.kind) for shot in replay.shots] == [
        (p.day, "video" if p.is_video else "photo") for p in picked
    ]
    # Held as long as the real run held them: its own `runs story`, titles' trims included.
    assert [shot.seconds for shot in replay.shots] == [
        float(m["seconds"])
        for m in _SHOT.finditer((RECORDINGS / "monthly_highlights" / "story.txt").read_text())
    ]


def test_a_picture_the_recording_left_out_keeps_the_recorded_reason(
    library_home: UserHome,
) -> None:
    recorded = _recorded("monthly_highlights")
    left_out = next(
        row
        for step in recorded["selection-trace"]["editorial_passes"]
        for row in step["rejected"]
        if row["asset_id"] in ACCOUNTS_BY_ID and not ACCOUNTS_BY_ID[row["asset_id"]].is_video
    )
    replay = cut(library_home, *_MONTH, env={RECORDING_ENV: "monthly_highlights"})

    why = library_home.run("runs", "why", left_out["asset_id"], "--run", replay.run_id)

    assert why.returncode == 0, why.explain()
    assert left_out["reason"] in why.stdout, why.stdout
