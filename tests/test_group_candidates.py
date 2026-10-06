"""GroupCandidateDetector: a saved group proposes like MultiPersonDetector's pairs."""

from __future__ import annotations

from datetime import date

from immich_memories.api.person_expression import PersonExpression
from immich_memories.automation.candidates import CandidateCategory
from immich_memories.automation.group_candidates import GroupCandidateDetector
from immich_memories.people.groups import SavedGroup

KIDS = PersonExpression.parse('"kid-a" OR "kid-b"')


def _config():
    from unittest.mock import MagicMock

    return MagicMock()


def test_a_saved_group_proposes_a_multi_person_candidate_with_its_expression():
    groups = [SavedGroup("Kids", KIDS)]
    today = date(2026, 8, 1)

    result = GroupCandidateDetector().detect(
        {}, [], set(), _config(), today, groups=groups, person_asset_counts={"kid-a": 10}
    )

    assert len(result) == 1
    candidate = result[0]
    assert candidate.category is CandidateCategory.MULTI_PERSON
    assert candidate.memory_type == "multi_person"
    assert candidate.extra_params["person_expression"] == KIDS.to_dict()
    assert set(candidate.person_names) == set(KIDS.leaf_values)
    assert candidate.date_range_start.year == today.year - 1


def test_a_group_with_zero_known_assets_is_skipped():
    groups = [SavedGroup("Kids", KIDS)]

    result = GroupCandidateDetector().detect(
        {},
        [],
        set(),
        _config(),
        date(2026, 8, 1),
        groups=groups,
        person_asset_counts={"kid-a": 0, "kid-b": 0},
    )

    assert result == []


def test_a_group_with_no_count_data_still_proposes():
    """No asset-count read (spotlight disabled) is not evidence a group is empty."""
    groups = [SavedGroup("Kids", KIDS)]

    result = GroupCandidateDetector().detect(
        {}, [], set(), _config(), date(2026, 8, 1), groups=groups, person_asset_counts={}
    )

    assert len(result) == 1


def test_a_generated_group_key_is_skipped_next_time():
    groups = [SavedGroup("Kids", KIDS)]
    first = GroupCandidateDetector().detect(
        {}, [], set(), _config(), date(2026, 8, 1), groups=groups, person_asset_counts={}
    )

    again = GroupCandidateDetector().detect(
        {},
        [],
        {first[0].memory_key},
        _config(),
        date(2026, 8, 1),
        groups=groups,
        person_asset_counts={},
    )

    assert again == []


def test_no_groups_yields_no_candidates():
    assert GroupCandidateDetector().detect({}, [], set(), _config(), date(2026, 8, 1)) == []


def test_a_group_whose_members_have_no_pictures_last_year_is_not_proposed():
    result = GroupCandidateDetector().detect(
        {},
        [],
        set(),
        _config(),
        date(2026, 8, 1),
        groups=[SavedGroup("Kids", KIDS)],
        person_asset_counts={"kid-a": 0, "kid-b": 0},
    )

    assert result == []
