"""A shareable film on a captioning tier is decided by its captions, not by the draft's rules (#2135)."""

from dataclasses import replace

from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_shareability import SHAREABLE
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.config_loader import Config
from tests.test_editorial_duration_planner_integration import source


def _unread_shareable_month(tmp_path):
    """A captioning-tier shareable month whose pictures carry no detector rows yet."""
    captured = source(tmp_path, seconds=60, pictures=12)
    return replace(
        captured,
        config=Config(tier="gpu", editorial={"preparation": {"tier": "full"}}),
        audience=SHAREABLE,
        audience_annotations={
            asset_id: replace(row, heads=())
            for asset_id, row in captured.audience_annotations.items()
        },
    )


def test_the_draft_of_a_captioned_shareable_film_reaches_the_reading(tmp_path):
    captured = _unread_shareable_month(tmp_path)
    drafts = []

    # WHY: refinement acquires captions and loads Laya, external providers; the test only
    # asks whether the draft hands it anything to read.
    def refine(refined_source, draft):
        drafts.append(draft)
        return refined_source, StructurePlannerPorts(
            judge=NoModelJudge(),
            rules=RuleStructureReader(refined_source),
            thumbnail_hash=lambda _: None,
            draft=draft,
        )

    result = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            rules=RuleStructureReader(captured),
            thumbnail_hash=lambda _: None,
            refine=refine,
        ),
    )

    assert drafts and drafts[0].carriers
    # The draft cut for the family; the film itself is still gated at its own level, and
    # with no reading to clear them, nothing unread reaches a shareable film.
    assert result.plan["shareability"]["audience"] == "shareable"
    assert result.plan["carriers"] == []
