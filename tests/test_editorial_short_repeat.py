"""A long requested duration cannot protect a repeated scene from the final review."""

import hashlib

import numpy as np

from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from tests.editorial_story_fixtures import ControlledStoryJudge
from tests.test_editorial_duration_planner_integration import source


def test_a_ten_minute_request_keeps_a_short_film_free_of_scene_repeats(tmp_path):
    captured = source(tmp_path, seconds=600, pictures=20)
    prints = {f"picture-{n:03}": np.eye(20)[0 if n == 1 else n] for n in range(20)}
    plan = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda a: hashlib.sha256(a.encode()).hexdigest()[:16],
            scene_print=prints.get,
        ),
    ).plan

    kept = {row["asset_id"] for row in plan["carriers"]}
    assert "picture-000" in kept and "picture-001" not in kept
    assert plan["content_seconds"] < 600
    assert plan["duration_realization"]["status"] == "editorial_shortfall"
