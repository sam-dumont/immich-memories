"""A custom date range with no written subject is a film of its window, not of boilerplate."""

from datetime import datetime

from immich_memories.analysis.editorial_block_votes import (
    WORTH_CRITERION_V44,
    worth_criterion_v44,
)
from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_product_brief import build_editorial_brief
from immich_memories.timeperiod import DateRange

_WINDOW = (DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20, 23, 59, 59)),)


def _intent(base=None):
    brief = build_editorial_brief("custom", _WINDOW, base=base)
    return build_editorial_intent("custom", _WINDOW, brief=brief)


def test_a_plain_custom_range_asks_its_questions_about_the_window():
    intent = _intent()

    assert intent.subject is None
    assert "binding subject" not in intent.prompt_block()
    assert "2024-03-10..2024-05-20" in intent.prompt_block()
    assert "requested subject" not in intent.prompt_block() + intent.story_prompt_block()
    assert worth_criterion_v44("custom", intent.subject) == (WORTH_CRITERION_V44, "")


def test_a_written_subject_still_binds_the_custom_film():
    intent = _intent("Follow the red bicycle across the spring.")

    assert intent.subject == "Follow the red bicycle across the spring."
    assert "binding subject: Follow the red bicycle" in intent.prompt_block()
    assert "requested subject" in intent.story_prompt_block()
    assert worth_criterion_v44("custom", intent.subject)[1] == "subject-v1"


FARMHOUSE = (44.0, 7.0, "Farmhouse", "Homeland")
WORKS = "Exposed brick behind stripped plaster in a room under construction."


def _renovation_spring(tmp_path, brief_of):
    """Four family Saturdays at home and, three days after each, a visit to the works at the
    farmhouse: two frames of an empty room each, nobody in them."""
    from dataclasses import replace
    from datetime import date, timedelta

    from immich_memories.analysis.annotation_lines import AssetAnnotationLine
    from tests.editorial_film_fixtures import HOME, Day, film_source

    days = []
    for week in range(4):
        saturday = date(2024, 3, 2) + timedelta(days=7 * week)
        days += [
            Day(saturday, f"Family day {week + 1}", HOME),
            Day(saturday + timedelta(days=3), f"Works {week + 1}", FARMHOUSE),
        ]
    source = film_source(
        tmp_path, days, seconds=40, span=(date(2024, 3, 1), date(2024, 4, 30)), product="custom"
    )
    works = set()
    for asset_id, row in list(source.audience_annotations.items()):
        if int(asset_id[1:4]) % 2:
            works.add(asset_id)
            line = f"{row.text.split(' | ')[0]} | {WORKS} | at Farmhouse, Homeland"
            source.annotations[asset_id] = line
            source.audience_annotations[asset_id] = AssetAnnotationLine(
                asset_id,
                line,
                description=WORKS,
                heads=(("nsfw_marqo", "no"), ("people", "none"), ("location", "indoor")),
            )
    brief = brief_of(source.case.ranges)
    source = replace(
        source,
        case=replace(source.case, brief=brief),
        intent=build_editorial_intent("custom", source.case.ranges, brief=brief),
    )
    return source, works


def _no_model_cut(source) -> list[str]:
    from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
    from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
    from immich_memories.analysis.editorial_structure_planner import plan_structure

    plan = plan_structure(
        source,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            # WHY: no preview hashes in a fixture library; the duplicate review has nothing to read.
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
        ),
    ).plan
    return [c["asset_id"] for c in plan["carriers"]]


def test_a_renovation_film_shows_the_works_though_nobody_is_in_them(tmp_path):
    source, works = _renovation_spring(tmp_path, lambda _ranges: "The farmhouse renovation")

    shots = _no_model_cut(source)

    assert works & set(shots)


def test_a_film_of_the_window_still_refuses_empty_rooms_as_context(tmp_path):
    source, works = _renovation_spring(
        tmp_path, lambda ranges: build_editorial_brief("custom", ranges)
    )

    shots = _no_model_cut(source)

    assert not works & set(shots)
