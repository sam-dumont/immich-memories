"""#2042: capacity counts only the moments a story can show distinctly, and only when it
matters.

A story's capture groups can be inflated by the upstream clustering: two groups more than
five minutes apart are two "moments" even when they show the same scene a few minutes later.
`distinct_choices` folds those before a single slot is granted, by the final duplicate
review's own hash (`hash_repeat_relation`) and scene rule. `capacity_choices` gates that fold:
a story whose unfolded grant was never going to exceed its distinct count keeps today's exact,
unfolded allocation untouched, so a clean film (nothing the final review would remove) never
changes.
"""

from immich_memories.analysis.editorial_story_capacity import capacity_choices, distinct_choices
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_slots import PartitionedSlots
from immich_memories.analysis.subject_framing import SubjectVisibility


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

    kept = distinct_choices(choices, _units(a="t1", b="t2"), "S1", None, None)

    assert kept == choices


def test_a_further_group_the_scene_rule_calls_a_repeat_folds_into_the_one_kept():
    choices = [_choice("c1", "a"), _choice("c2", "b"), _choice("c3", "c")]

    kept = distinct_choices(
        choices, _units(a="t1", b="t2", c="t3"), "S1", hash_alike=None, scene_alike=_always(True)
    )

    assert [c.key for c in kept] == ["c1"]
    assert kept[0].members == ["a", "b", "c"]  # still reachable as depth, not as a new slot


def test_the_hash_rule_alone_also_folds_a_repeat():
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = distinct_choices(
        choices, _units(a="t1", b="t2"), "S1", hash_alike=_always(True), scene_alike=None
    )

    assert [c.key for c in kept] == ["c1"]


def test_a_group_neither_rule_calls_a_repeat_keeps_its_own_slot():
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = distinct_choices(
        choices,
        _units(a="t1", b="t2"),
        "S1",
        hash_alike=_always(False),
        scene_alike=_always(False),
    )

    assert [c.key for c in kept] == ["c1", "c2"]


def test_an_unknown_hash_answer_falls_back_to_the_scene_rule():
    """A cached hash that cannot answer (no preview) must not block the scene rule from
    folding a repeat the hash alone could not see."""
    choices = [_choice("c1", "a"), _choice("c2", "b")]

    kept = distinct_choices(
        choices,
        _units(a="t1", b="t2"),
        "S1",
        hash_alike=_always(None),
        scene_alike=_always(True),
    )

    assert [c.key for c in kept] == ["c1"]


def test_a_starred_choice_is_never_folded_into_a_plain_one():
    choices = [_choice("c1", "a"), _choice("c2", "b")]
    units = _units(a="t1", b="t2")
    units["b"][1]["favourite"] = True

    kept = distinct_choices(choices, units, "S1", hash_alike=_always(True), scene_alike=None)

    assert [c.key for c in kept] == ["c1", "c2"]


def _story_units(count: int) -> dict[str, list[dict]]:
    return {
        f"c{n}": [{"asset_id": f"a{n}", "taken": f"2030-05-0{n + 1}T09:00:00", "kind": "still"}]
        for n in range(count)
    }


def _flat_story_units(story_key: str, count: int) -> dict[str, list[dict]]:
    return {story_key: [row[0] for row in _story_units(count).values()]}


def _unit_by_asset(count: int) -> dict[str, tuple[None, dict]]:
    return {
        f"a{n}": (None, {"asset_id": f"a{n}", "taken": f"2030-05-0{n + 1}T09:00:00"})
        for n in range(count)
    }


def test_a_story_whose_grant_never_reaches_past_its_distinct_count_keeps_its_raw_allocation():
    """Three raw capture groups, two of them one scene: a film with exactly as many slots as
    the story's distinct count never needs the fold to stay within it."""
    stories = [{"key": "S1", "weight": "minor"}]
    story_units = _flat_story_units("S1", 3)
    parts = PartitionedSlots(_unit_by_asset(3))

    choices_of, groups_offered = capacity_choices(
        stories,
        story_units,
        _unit_by_asset(3),
        parts,
        slots=2,
        hash_alike=None,
        scene_alike=lambda c, k: c["asset_id"] != k["asset_id"] and c["asset_id"] != "a2",
        quality=lambda _a: 0.0,
        flagged=lambda _a: False,
        life=lambda _a: True,
        plays=lambda _u: False,
        subject=lambda _a: SubjectVisibility(0, 0.0),
        rank=None,
        withhold=None,
    )

    assert groups_offered["S1"] == 3
    assert len(choices_of["S1"]) == 3  # the gate left it unfolded: the grant never needed it


def test_a_story_whose_grant_would_exceed_its_distinct_count_is_folded():
    """The same three raw groups, but a bigger film with nothing else to fund: `_deepen`
    would hand this one story its whole budget, past what it can show distinctly, so the
    gate folds it first and the film stays short rather than repeat a scene."""
    stories = [{"key": "S1", "weight": "major"}]
    story_units = _flat_story_units("S1", 3)
    parts = PartitionedSlots(_unit_by_asset(3))

    choices_of, _groups_offered = capacity_choices(
        stories,
        story_units,
        _unit_by_asset(3),
        parts,
        slots=5,
        hash_alike=None,
        scene_alike=lambda c, k: c["asset_id"] != k["asset_id"] and c["asset_id"] != "a2",
        quality=lambda _a: 0.0,
        flagged=lambda _a: False,
        life=lambda _a: True,
        plays=lambda _u: False,
        subject=lambda _a: SubjectVisibility(0, 0.0),
        rank=None,
        withhold=None,
    )

    assert len(choices_of["S1"]) == 2  # folded: a2 is a repeat of a0, by the scene rule
