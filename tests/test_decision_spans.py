"""A run's trace says why the film is what it is: each selection decision, and the film itself."""

from __future__ import annotations

import pytest

from immich_memories.analysis.corpus import trace
from immich_memories.analysis.corpus.records import DecisionProvenance, PassTrace, TraceDecision
from immich_memories.analysis.runtime.smart_pipeline import ClipWithSegment
from immich_memories.api.models import VideoClipInfo
from immich_memories.tracking import otel, timing
from tests.conftest import make_asset
from tests.otel_receiver import receiving


@pytest.fixture
def collector(monkeypatch):
    with receiving(monkeypatch) as received:
        otel.setup()
        yield received


def _candidate(asset_id: str, *, favorite: bool = False) -> ClipWithSegment:
    asset = make_asset(asset_id, original_file_name=f"{asset_id}.MOV", is_favorite=favorite)
    clip = VideoClipInfo(asset=asset, duration_seconds=4.0, width=1920, height=1080)
    return ClipWithSegment(clip=clip, start_time=0.0, end_time=4.0, score=0.5)


def test_a_selection_stage_is_a_span_with_what_it_dropped_and_why(collector):
    kept, near_copy, blurry = _candidate("a1", favorite=True), _candidate("b2"), _candidate("c3")

    with trace.tracing(), timing.span("selection"):
        trace.record(
            "near-duplicates",
            [kept, near_copy, blurry],
            [kept],
            reasons=["2 near-duplicate clips"],
            notes={"b2": "same scene as a1"},
        )

    spans = collector.named()
    decision = spans["select near-duplicates"]
    assert decision["parent"] == spans["selection"]["span_id"]
    attributes = decision["attributes"]
    assert attributes["selection.input"] == 3
    assert attributes["selection.kept"] == 1
    assert attributes["selection.dropped"] == 2
    assert attributes["selection.favorites.in"] == 1
    assert attributes["selection.favorites.out"] == 1
    assert attributes["selection.reasons"] == ["2 near-duplicate clips"]
    dropped = {
        event["immich.asset.id"]: event
        for name, event in decision["events"]
        if name == "clip.dropped"
    }
    assert set(dropped) == {"b2", "c3"}
    assert dropped["b2"]["clip.reason"] == "same scene as a1"
    assert dropped["b2"]["clip.facts"].startswith("b2.MOV")


def test_an_editorial_pass_is_a_span_with_its_model_and_each_rejection(collector):
    provenance = DecisionProvenance(
        pass_name="cull",  # noqa: S106 - an editorial pass name, not a password
        pass_version="3",  # noqa: S106 - a version number, not a password
        schema_version="1",
        model_identity="gemma-e4b",
        input_ids=("a1", "b2"),
        sheet_hashes=(),
        request_key="k",
        cache_hit=True,
    )
    pass_trace = PassTrace(
        name="cull",
        input_ids=("a1", "b2"),
        kept_ids=("a1",),
        rejected=(TraceDecision("b2", "eyes closed"),),
        unresolved=(),
        duration_before=12.0,
        duration_after=6.0,
        provenance=provenance,
    )

    with trace.tracing(), timing.span("selection"):
        trace.record(pass_trace)

    attributes = collector.named()["select cull"]["attributes"]
    assert attributes["selection.input"] == 2
    assert attributes["selection.kept"] == 1
    assert attributes["selection.dropped"] == 1
    assert attributes["selection.seconds.before"] == 12.0
    assert attributes["selection.seconds.after"] == 6.0
    assert attributes["gen_ai.request.model"] == "gemma-e4b"
    assert attributes["selection.cache_hit"] is True
    events = collector.named()["select cull"]["events"]
    assert ("clip.dropped", {"immich.asset.id": "b2", "clip.reason": "eyes closed"}) in events


def test_the_run_span_carries_the_film_it_made(collector):
    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with observe_run(
        open_store(), source="manual", memory_type="monthly_highlights", capture_system=False
    ) as tracker:
        tracker.complete_run(clips_analyzed=40, clips_selected=12)

    attributes = collector.named()["run"]["attributes"]
    assert attributes["memory.type"] == "monthly_highlights"
    assert attributes["film.clips.analyzed"] == 40
    assert attributes["film.clips.selected"] == 12
    assert attributes["film.target_seconds"] > 0
    assert attributes["film.delivery"] == "not_requested"
