"""Episode lookup conserves subset-scan results, including malformed inputs."""

from dataclasses import asdict, fields, replace
from itertools import combinations
from types import SimpleNamespace

import pytest

from immich_memories.analysis.selection_source_groups import (
    EditorialGroup,
    EpisodeMembershipIndex,
)


def _group(name, *ids):
    return EditorialGroup(name, tuple(SimpleNamespace(asset_id=asset_id) for asset_id in ids))


@pytest.mark.parametrize(
    "groups",
    [
        (),
        (_group("one", "a", "b"), _group("two", "c")),
        (_group("one", "a", "b"), _group("two", "b", "c")),
        (_group("same", "a", "b"), _group("same", "a", "b")),
        (_group("empty"), _group("repeated", "a", "a")),
    ],
)
def test_episode_index_matches_full_subset_scan_for_all_member_combinations(groups):
    index = EpisodeMembershipIndex(groups)
    for length in range(5):
        for ids in combinations(("a", "b", "c", "unknown"), length):
            expected = tuple(
                position
                for position, group in enumerate(groups)
                if set(ids).issubset(group.candidate_ids)
            )
            assert index.carrying_positions(ids) == expected
            assert index.carrying_positions(tuple(reversed(ids)) + ids) == expected


def test_cached_ids_keep_dataclass_contract_and_replacement_membership():
    group = _group("one", "b", "a")
    before = asdict(group)
    ids = group.candidate_ids
    assert ids == ("b", "a")
    assert group.candidate_ids is ids
    assert asdict(group) == before
    assert [field.name for field in fields(group)] == ["group_id", "candidates"]
    assert group == _group("one", "b", "a")
    assert replace(group, candidates=_group("other", "c").candidates).candidate_ids == ("c",)
