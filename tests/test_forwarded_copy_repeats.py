"""Forwarded copies go through the same duplicate review as camera pictures.

Two copies of one hay-bale scene, received at 05:23 and 18:02 on one day, both stayed in a
film: the review reads two frames of one day as one scene only within one moment of each
other, by capture time. A copy's time is when it arrived, not when it was shot.
"""

from __future__ import annotations

import numpy as np

from immich_memories.analysis.selection.final_hash_review import scene_pair_relation

ONE_SCENE = {"a": np.array([1.0, 0.0]), "b": np.array([0.89, 0.456])}


def _carrier(asset_id: str, taken: str, *, forwarded: bool) -> dict:
    row = {"asset_id": asset_id, "taken": taken, "kind": "still", "story_episode": "S1"}
    return row | ({"forwarded": True} if forwarded else {})


def test_two_copies_of_one_scene_received_hours_apart_are_one_scene():
    same_scene = scene_pair_relation(ONE_SCENE.get)

    assert same_scene(
        _carrier("b", "2024-08-25T18:02:49+00:00", forwarded=True),
        _carrier("a", "2024-08-25T05:23:11+00:00", forwarded=True),
    )


def test_two_camera_frames_hours_apart_on_one_day_stay_two_moments():
    same_scene = scene_pair_relation(ONE_SCENE.get)

    assert not same_scene(
        _carrier("b", "2024-08-25T18:02:49+00:00", forwarded=False),
        _carrier("a", "2024-08-25T05:23:11+00:00", forwarded=False),
    )
