"""#2042: a story's unfunded moments only ever come from a weighed story.

A story the synthesis gave no weight is never the household's own account of the period; a
refill must not make it one, whether the slot is freed inside the planner's own allocation or
by the final duplicate review afterwards.
"""

from immich_memories.analysis.editorial_story_replacement_pool import unfunded_pool
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice


def _choice(key: str, primary: str) -> DepictedChoice:
    return DepictedChoice(
        key=key, episode="S", taken="2024-06-01T09:00:00", content="", primary=primary
    )


def test_a_none_weighted_storys_moments_never_enter_the_unfunded_pool():
    stories = [
        {"key": "S1", "weight": "minor"},
        {"key": "S2", "weight": "none"},
    ]
    choices_of = {"S1": [_choice("c1", "a")], "S2": [_choice("c2", "b")]}
    chosen_by_story = {"S1": [], "S2": []}

    pool = unfunded_pool(stories, choices_of, chosen_by_story)

    assert pool == ["a"]


def test_a_weighed_storys_chosen_moments_are_not_unfunded():
    stories = [{"key": "S1", "weight": "major"}]
    choices_of = {"S1": [_choice("c1", "a"), _choice("c2", "b")]}
    chosen_by_story = {"S1": ["c1"]}

    pool = unfunded_pool(stories, choices_of, chosen_by_story)

    assert pool == ["b"]
