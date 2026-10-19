"""Selection prepares candidates per decision, not per candidate (#2686)."""

import hashlib

import numpy as np
import pytest

from immich_memories.analysis.audience import shareability
from immich_memories.analysis.film.contract import StructurePlannerPorts
from immich_memories.analysis.lookahead import Lookahead
from immich_memories.analysis.structure.planner import plan_structure
from tests.editorial_story_fixtures import ControlledStoryJudge
from tests.test_editorial_duration_planner_integration import source


def _select(tmp_path, screens):
    captured = source(tmp_path, seconds=60, pictures=20)
    rounds: list[list[str]] = []
    inspected: set[str] = set()

    # WHY: the preparation boundary is where rounds are paid for; the planner, the gates and
    # the refill are real. A round is one call that prepares something not yet prepared.
    def prepare(rows):
        fresh = {row["asset_id"] for row in rows} - inspected
        inspected.update(fresh)
        for asset_id in fresh & set(screens):
            captured.annotations[asset_id] += " | screen=yes"
        if fresh:
            rounds.append(sorted(fresh))
        return bool(fresh)

    prints = {f"picture-{n:03}": np.eye(20)[0 if n == 1 else n] for n in range(20)}
    plan = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda a: hashlib.sha256(a.encode()).hexdigest()[:16],
            scene_print=prints.get,
            prepare_candidates=prepare,
        ),
    ).plan
    return [row["asset_id"] for row in plan["carriers"]], rounds


def _one_by_one(monkeypatch):
    """Selection as it was: every candidate its own round."""
    real = shareability.apply_gate
    monkeypatch.setattr(
        shareability,
        "apply_gate",
        lambda *args, **kwargs: real(*args, **{k: v for k, v in kwargs.items() if k != "prepare"}),
    )
    monkeypatch.setattr(Lookahead, "reach", lambda _self, _position: None)


SCREEN_SETS = [
    pytest.param(("picture-015",), id="one-refused"),
    pytest.param((), id="none-refused"),
    pytest.param(("picture-003", "picture-015", "picture-016"), id="several-refused"),
]


@pytest.mark.parametrize("screens", SCREEN_SETS)
def test_batching_prepares_in_fewer_rounds_and_admits_the_same_pictures(
    tmp_path, monkeypatch, screens
):
    batched_cut, batched_rounds = _select(tmp_path / "batched", screens)
    _one_by_one(monkeypatch)
    single_cut, single_rounds = _select(tmp_path / "single", screens)

    assert batched_cut == single_cut
    assert len(batched_rounds) < len(single_rounds)


def test_a_cold_period_prepares_its_cut_in_a_handful_of_rounds(tmp_path):
    cut, rounds = _select(tmp_path, ("picture-015",))

    # Seventeen pictures were prepared one at a time before: one round for the cut, then one
    # per refill attempt for the picture that was refused and the one that took its place.
    assert cut[0] == "picture-000" and "picture-015" not in cut and "picture-016" in cut
    assert len(rounds) == 3
    assert len(rounds[0]) == 15


def test_the_lookahead_prepares_in_doubling_windows_and_only_as_far_as_the_walk_goes():
    rounds = []
    ahead = Lookahead(list(range(20)), rounds.append)

    for position in range(6):
        ahead.reach(position)

    assert rounds == [[0], [1], [2, 3], [4, 5, 6, 7]]
