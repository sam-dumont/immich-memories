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


def test_startup_before_the_saved_run_counts_toward_the_wall_it_covers():
    """The run record starts after imports; the root span starts at process start."""
    spans = [
        Span(1, "run", None, 0, 100),
        Span(2, "startup", 1, 0, 5),
        Span(3, "pipeline", 1, 5, 94),
    ]
    assert uncovered_seconds(spans, 95) == 1


def test_stage_clock_publishes_one_overall_estimate_from_spans(monkeypatch):
    from immich_memories.operations.cut_progress import StageClock, StageUpdate

    # WHY: advance the wall clock without a slow sleep in the progress test.
    moments = iter([0.0, 4.0])
    monkeypatch.setattr("immich_memories.tracking.timing.time.perf_counter", lambda: next(moments))
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


def test_defaults_fill_stages_history_never_measured_and_skipped_stages_stay_out():
    defaults = {"download": 10.0, "assembly": 30.0, "music": 0.0}
    plan = SpanPlan(
        [Span(1, "assembly", None, 0, 90), Span(2, "music", None, 90, 60)], defaults=defaults
    )
    assert plan.weights == {"download": 10.0, "assembly": 90.0, "music": 0.0}
    halfway = plan.estimate("download", fraction=0.5)
    assert halfway.fraction == 5 / 100
    assert halfway.remaining_seconds is None  # download itself is only a guess
    measured = plan.estimate("assembly", fraction=0.5, remaining=45)
    assert measured.remaining_seconds == 45


def test_two_runs_with_different_counts_share_one_stage_name():
    from immich_memories.analysis.editorial_structure_finishing import announce_count
    from immich_memories.operations.cut_progress import StageClock, announcing_stages
    from immich_memories.tracking.timing import collecting

    names = []
    for pictures in (40, 1200):
        with collecting() as collected, announcing_stages((clock := StageClock()).measure):
            announce_count(pictures, "kept")
            clock.finish()
        names.extend(span.name for span in collected.spans)
    assert len(names) == 2
    assert names[0] == names[1]


def test_period_account_months_and_batch_waits_keep_stable_keys():
    from immich_memories.operations.cut_progress import StageUpdate

    march = StageUpdate("Reading the period account: 2024-03")
    april = StageUpdate("Reading the period account: 2024-04")
    assert march.stage_key == april.stage_key
    assert "2024" not in march.stage_key


def test_counted_stage_history_scales_by_pictures_not_by_its_own_packs():
    """Ten packs took 100 s for 1000 pictures; the next 1000-picture run is not 10,000 s."""
    from immich_memories.operations.cut_progress import StageClock, StageUpdate
    from immich_memories.tracking.timing import collecting

    now = [0.0]
    with collecting(now=lambda: now[0]) as first:
        clock = StageClock(items=1000)
        for done in range(11):
            clock.measure(StageUpdate("event evidence", done=done, total=10, verb="Reading"))
            now[0] += 10.0
        clock.finish()
    plan = SpanPlan(first.spans, items=1000)
    estimate = plan.estimate(first.spans[0].name, fraction=0.0)
    assert 90 <= estimate.remaining_seconds <= 120


def test_the_span_tree_shows_each_measured_peak():
    from immich_memories.tracking.span_progress import span_tree
    from immich_memories.tracking.timing import Span

    spans = [
        Span(1, "run", None, 0, 10.0, peak_rss=512 * 2**20, peak_tree_rss=2048 * 2**20),
        Span(2, "render.assembly", 1, 1, 9.0),
    ]
    lines = span_tree(spans, 10.0)
    assert lines[0] == "run: 10.000 s, peak 512 MB (with children 2048 MB)"
    assert lines[1] == "  render.assembly: 9.000 s"
