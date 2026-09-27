"""A valid fallback film must not present its model pass as fully successful."""

import json

import pytest

from immich_memories.analysis.editorial_people import adapt_editorial_people
from immich_memories.analysis.editorial_runtime import EditorialRunContext
from immich_memories.analysis.editorial_runtime_backend import ProductionPostCardBackend
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.llm_wire import LLMIncompleteResponse
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.selection_trace import Trace
from tests.test_editorial_story_first_planner import StoryJudge, make_source
from tests.test_episode_demand import answer, demand_for


@pytest.mark.parametrize("recover", [False, True])
def test_final_plan_and_trace_report_the_latest_demand_health(tmp_path, recover):
    asked = []

    # WHY: replace only the provider boundary; the reader, store and planner remain real.
    def incomplete(prompt):
        if len(asked) == 1:
            raise LLMIncompleteResponse('{"episodes":[')
        return answer(prompt)

    captured = make_source(tmp_path, seconds=24)
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(date_ranges=captured.case.ranges)),
        EditorialDependencies(source_fetcher=lambda _scope: tuple(captured.assets.values())),
    )
    demand, _prepared = demand_for(tmp_path, asked, respond=incomplete, prepared=prepared)
    demand.readings_for(list(captured.assets)[:1])
    if recover:
        demand.readings_for(list(captured.assets)[:1])
    captured.config.editorial.reader = "model"
    captured.config.llm.model = "a-model"
    case = captured.case
    backend = ProductionPostCardBackend(
        config=captured.config,
        context=EditorialRunContext(
            case.key,
            case.label,
            case.product,
            case.ranges,
            case.target_seconds,
            captured.artifact_dir,
        ),
        people=adapt_editorial_people({}),
        thumbnail_cache=object(),
        store_path=tmp_path / "annotations.sqlite",
        # WHY: fixed model judgments and absent fixture thumbnails isolate run persistence.
        ports=EditorialRuntimePorts(
            structure_ports_factory=lambda _source: StructurePlannerPorts(
                judge=StoryJudge(),
                thumbnail_hash=lambda _asset: None,
            )
        ),
        episode_demand=demand,
    )
    trace = Trace()

    result = backend.edit(captured, trace=trace)

    assert result.selections
    plan = json.loads((captured.artifact_dir / "plan.private.json").read_text())
    health = plan["episode_reading_health"]
    assert health["status"] == ("complete" if recover else "degraded")
    assert health["unavailable_episodes"] == (0 if recover else 1)
    assert health["episodes"][0]["status"] == ("recovered" if recover else "unavailable")
    assert (
        any("1 demanded episode" in warning and "fallback" in warning for warning in trace.warnings)
        != recover
    )
