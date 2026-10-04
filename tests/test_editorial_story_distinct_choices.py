"""#2042: capacity counts only the moments a story can show distinctly.

A story's capture groups can be inflated by the upstream clustering: two groups more than
five minutes apart are two "moments" even when they show the same scene a few minutes later.
`_distinct_choices` folds those before a single slot is granted, by the same hash-and-scene
rule the final duplicate review applies over the finished cut.
"""

from immich_memories.analysis.editorial_story_planner import _distinct_choices
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice


def _choice(key: str, primary: str, *alternatives: str) -> DepictedChoice:
    return DepictedChoice(
        key=key,
        episode="S1",
        taken="2030-05-01T09:00:00",
        content="",
        primary=primary,
        alternatives=list(alternatives),
    )


def _units(**taken_by_asset: str) -> dict[str, tuple[None, dict]]:
    return {
        asset_id: (None, {"asset_id": asset_id, "taken": taken, "kind": "still"})
        for asset_id, taken in taken_by_asset.items()
    }


def _always(verdict: bool | None):
    return lambda _candidate, _keeper: verdict


def test_with_no_rule_every_capture_group_counts_as_its_own_moment():
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = _distinct_choices(choices, _units(a="t1", b="t2"), "S1", None, None)

    assert kept == choices


def test_a_further_group_the_scene_rule_calls_a_repeat_folds_into_the_one_kept():
    choices = [_choice("c1", "a"), _choice("c2", "b"), _choice("c3", "c")]

    kept = _distinct_choices(
        choices, _units(a="t1", b="t2", c="t3"), "S1", looks_alike=None, scene_alike=_always(True)
    )

    assert [c.key for c in kept] == ["c1"]
    assert kept[0].members == ["a", "b", "c"]  # still reachable as depth, not as a new slot


def test_the_hash_rule_alone_also_folds_a_repeat():
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = _distinct_choices(
        choices, _units(a="t1", b="t2"), "S1", looks_alike=_always(True), scene_alike=None
    )

    assert [c.key for c in kept] == ["c1"]


def test_a_group_neither_rule_calls_a_repeat_keeps_its_own_slot():
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = _distinct_choices(
        choices,
        _units(a="t1", b="t2"),
        "S1",
        looks_alike=_always(False),
        scene_alike=_always(False),
    )

    assert [c.key for c in kept] == ["c1", "c2"]


def test_an_unknown_hash_answer_falls_back_to_the_scene_rule():
    """A cached hash that cannot answer (no preview) must not block the scene rule from
    folding a repeat the hash alone could not see."""
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = _distinct_choices(
        choices,
        _units(a="t1", b="t2"),
        "S1",
        looks_alike=_always(None),
        scene_alike=_always(True),
    )

    assert [c.key for c in kept] == ["c1"]
