"""The rules draft a model refines names its stories from the run's albums too (#2491)."""

from dataclasses import replace

from immich_memories.analysis.film.contract import StructurePlannerPorts
from immich_memories.analysis.stories.rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.structure.planner import plan_structure
from tests.test_editorial_duration_planner_integration import source


def test_the_draft_before_refinement_reads_the_runs_albums(tmp_path):
    captured = source(tmp_path, seconds=60, pictures=24)
    asked: list[tuple[str, ...]] = []

    def album_names(asset_ids):
        asked.append(tuple(asset_ids))
        return ("The road north",)

    ports = StructurePlannerPorts(
        judge=NoModelJudge(),
        rules=RuleStructureReader(captured, album_names=album_names),
        thumbnail_hash=lambda _: None,
    )
    drafted = []

    # WHY: the Full tier plans a rules draft over a narrowed pool, then hands it to the model;
    # stop at that hand-over to see which album lookup the draft's stories used.
    def refine(current, draft):
        drafted.append(draft)
        return current, replace(ports, draft=draft)

    plan_structure(captured, replace(ports, refine=refine))

    assert drafted, "the run never reached its refinement"
    assert asked, "the draft named its stories without the run's albums"
