"""Progress is based on measured stages, with no fabricated first-run estimate."""

from immich_memories.tracking.span_progress import SpanPlan, uncovered_seconds
from immich_memories.tracking.timing import Span


def test_plan_scales_picture_work_and_uses_current_stage_estimate():
    plan = SpanPlan(
        [
            Span(1, "preparation.detectors", None, 0, 20, items=10),
            Span(2, "selection", None, 20, 10),
        ],
        items=20,
    )
    estimate = plan.estimate("preparation.detectors", fraction=0.5, remaining=12)
    assert estimate.remaining_seconds == 22
    assert estimate.fraction == 20 / 42
    assert SpanPlan([], items=20).estimate("preparation.detectors", fraction=0.5) is None


def test_overlapping_children_are_not_double_counted_as_coverage():
    spans = [Span(1, "run", None, 0, 100), Span(2, "a", 1, 0, 50), Span(3, "b", 1, 40, 40)]
    assert uncovered_seconds(spans, 100) == 20


def test_stage_clock_publishes_one_overall_estimate_from_spans(monkeypatch):
    from immich_memories.operations.cut_progress import StageClock, StageUpdate

    # WHY: advance the wall clock without a slow sleep in the progress test.
    moments = iter([0.0, 4.0])
    monkeypatch.setattr(
        "immich_memories.operations.cut_progress.time.monotonic", lambda: next(moments)
    )
    clock = StageClock(
        plan=SpanPlan(
            [
                Span(1, "stage.analysis.detectors", None, 0, 20, items=10),
                Span(2, "stage.selection.Editing", None, 20, 10),
            ],
            items=20,
        )
    )
    clock.measure(StageUpdate("detectors", "analysis", 0, 20))
    update = clock.measure(StageUpdate("detectors", "analysis", 10, 20))
    assert update.total_remaining_seconds == 14
    assert update.total_fraction == 20 / 34


def test_unseen_stage_keeps_the_measured_total_bar_without_inventing_an_eta():
    from immich_memories.operations.cut_progress import StageClock, StageUpdate

    clock = StageClock(plan=SpanPlan([Span(1, "stage.analysis.detectors", None, 0, 20)]))
    known = clock.measure(StageUpdate("detectors", "analysis", 5, 10))
    unseen = clock.measure(StageUpdate("New reader stage", "selection"))
    assert unseen.total_fraction == known.total_fraction
    assert unseen.total_remaining_seconds is None
