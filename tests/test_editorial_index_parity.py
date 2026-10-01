"""Selection keeps its sealed bytes and picture order when indexes are reused."""

from immich_memories.analysis import (
    editorial_moment_wall,
    editorial_story_planner,
    editorial_structure_material,
    moment_cards,
)
from immich_memories.analysis.editorial_person_period_facts import person_period_facts
from immich_memories.analysis.selection_source_groups import EditorialGroup
from tests.test_editorial_duration_planner_integration import run
from tests.test_editorial_story_arrivals import _film, _PromptJudge


class _SubsetScan:
    """The former per-moment scan, kept only as the comparison oracle."""

    def __init__(self, groups):
        self.groups = groups

    def carrying_positions(self, asset_ids):
        members = set(asset_ids)
        return tuple(
            position
            for position, group in enumerate(self.groups)
            if members.issubset(group.candidate_ids)
        )


class _RepeatedPeople:
    def __init__(self, tables):
        self.tables = tables

    def facts(self, moment_ids):
        return person_period_facts(self.tables, moment_ids)


def test_sealed_wall_prompts_contract_and_selected_picture_order_match_previous_scans(
    tmp_path, monkeypatch
):
    # The real planner runs with deterministic editorial replies and an arrival
    # month, so reuse must preserve the people evidence in every affected prompt.
    with monkeypatch.context() as previous:
        previous.setattr(
            EditorialGroup,
            "candidate_ids",
            property(lambda group: tuple(candidate.asset_id for candidate in group.candidates)),
        )
        previous.setattr(editorial_moment_wall, "EpisodeMembershipIndex", _SubsetScan)
        previous.setattr(moment_cards, "EpisodeMembershipIndex", _SubsetScan)
        previous.setattr(editorial_story_planner, "PersonPeriodProjection", _RepeatedPeople)
        previous.setattr(editorial_structure_material, "PersonPeriodProjection", _RepeatedPeople)
        old_source = _film(tmp_path / "previous")
        old_judge = _PromptJudge()
        old_plan = run(old_source, old_judge)

    source = _film(tmp_path / "indexed")
    judge = _PromptJudge()
    plan = run(source, judge)

    assert source.wall_bytes == old_source.wall_bytes
    assert source.moment_asset_ids == old_source.moment_asset_ids
    assert judge.prompts == old_judge.prompts
    for field in ("carriers", "person_period_facts", "contract_key", "wall_sha256"):
        assert plan[field] == old_plan[field]
