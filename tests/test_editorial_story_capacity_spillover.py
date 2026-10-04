"""#2042: a story's grant is capped at the moments it can show distinctly, and the slack it
frees goes to another story's unfunded moments, through the real planner (`plan_structure`).

The burst day's two moments are each a near-identical set of frames (the depth a short film
spends its free slots on, `editorial_story_depth`): once the scene print says a further frame
of either moment is a repeat, that is all the burst day can distinctly show. The scavenger
hunt's moments are each their own scene, with room for every slot the burst day cannot use.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from tests.editorial_film_fixtures import Day, FilmJudge, film_source

MAY = (date(2030, 5, 1), date(2030, 5, 31))
HUNT_MOMENTS = 6
SLOTS = 8  # seconds=32 / NOMINAL_STILL_SECONDS(4)

_SCENE_IDS = ["burst-0", "burst-1"] + [f"hunt-{i}" for i in range(HUNT_MOMENTS)]
_SCENE_VECTORS = dict(zip(_SCENE_IDS, np.eye(len(_SCENE_IDS)), strict=True))


def _hash(asset_id: str) -> str:
    """Every frame hashes apart: the fix caps the burst day by its scene, not its hash."""
    return f"{abs(hash(asset_id)) % (1 << 64):016x}"


def _scene_print(asset_id: str) -> np.ndarray:
    """Every frame of one burst moment shares that moment's scene; the scavenger hunt's
    moments are each their own scene."""
    day, moment, _picture = asset_id.split("-")
    key = f"burst-{int(moment[1:])}" if day == "d000" else f"hunt-{int(moment[1:])}"
    return _SCENE_VECTORS[key]


def _film(tmp_path, *, hunt_moments: int = HUNT_MOMENTS):
    days = [
        Day(date(2030, 5, 1), "Birthday burst in the garden", moments=2),
        Day(date(2030, 5, 2), "Scavenger hunt around the house", moments=hunt_moments),
    ]
    return film_source(
        tmp_path,
        days,
        seconds=SLOTS * 4,
        span=MAY,
        pictures=6,
        picture_gap=timedelta(seconds=30),
    )


def _weigh(row: str) -> str:
    return "major" if "Birthday" in row else "minor"


def _run(source):
    judge = FilmJudge(weigh=_weigh)
    return plan_structure(
        source,
        StructurePlannerPorts(judge=judge, thumbnail_hash=_hash, scene_print=_scene_print),
    ).plan


def _episode_of(plan, *, title_has: str) -> dict:
    return next(row for row in plan["story"]["episodes"] if title_has in row["title"])


def test_the_burst_days_slack_spills_to_the_hunts_unfunded_moments_and_reaches_target(tmp_path):
    """The burst day cannot distinctly show more than its two moments; the slots that frees go
    to the scavenger hunt's distinct moments, in the planner's own funding order, reaching the
    full target with no two carriers of one scene."""
    plan = _run(_film(tmp_path))

    assert plan["story"]["slots"] == SLOTS
    assert len(plan["carriers"]) == SLOTS  # the full target, not a shortfall

    burst = _episode_of(plan, title_has="Birthday")
    hunt = _episode_of(plan, title_has="Scavenger")
    assert burst["granted"] == 2  # never more than the burst day can show distinctly
    assert hunt["granted"] == HUNT_MOMENTS  # the slack landed on real, distinct material

    scenes = [tuple(_scene_print(c["asset_id"])) for c in plan["carriers"]]
    assert len(set(scenes)) == len(scenes)  # no two carriers show the same scene


def test_a_burst_day_alone_stays_short_with_no_other_distinct_material(tmp_path):
    """No many-moment story to spill into: the film stays short of its target rather than
    hold a second carrier of a scene it already shows."""
    source = film_source(
        tmp_path,
        [Day(date(2030, 5, 1), "Birthday burst in the garden", moments=2)],
        seconds=SLOTS * 4,
        span=MAY,
        pictures=6,
        picture_gap=timedelta(seconds=30),
    )
    judge = FilmJudge(weigh=lambda _row: "major")
    plan = plan_structure(
        source,
        StructurePlannerPorts(judge=judge, thumbnail_hash=_hash, scene_print=_scene_print),
    ).plan

    assert plan["story"]["slots"] == SLOTS
    assert len(plan["carriers"]) == 2  # short of target: no repeat was kept to close the gap
