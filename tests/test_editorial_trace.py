"""Editorial decision tracing stays complete without changing chronology."""

from __future__ import annotations

from immich_memories.analysis.corpus.records import (
    DecisionProvenance,
    PassTrace,
    TraceDecision,
)
from immich_memories.analysis.corpus.trace import Trace, record, tracing


def _provenance(input_ids: tuple[str, ...]) -> DecisionProvenance:
    return DecisionProvenance(
        pass_name="cull",  # noqa: S106 - test-only pass identity
        pass_version="1",  # noqa: S106 - test-only pass identity
        schema_version="1",
        model_identity="test-model",
        input_ids=input_ids,
        sheet_hashes=("sheet-hash",),
        request_key="request-key",
        cache_hit=False,
    )


def test_editorial_pass_keeps_chronology_and_conserves_every_input() -> None:
    """A pass preserves the editor's order while accounting for every input."""
    trace = Trace()

    trace.record_editorial_pass(
        PassTrace(
            name="cull",
            input_ids=("late", "early", "middle"),
            kept_ids=("late", "middle"),
            rejected=(TraceDecision("early", "unusable exposure"),),
            unresolved=(),
            duration_before=12.0,
            duration_after=8.0,
            provenance=_provenance(("late", "early", "middle")),
        )
    )

    payload = trace.as_dict()

    assert payload["editorial_passes"][0]["kept_ids"] == ["late", "middle"]
    assert payload["editorial_passes"][0]["conservation"]["valid"] is True


def test_active_trace_accepts_an_editorial_pass_through_the_existing_adapter() -> None:
    """The module adapter remains the one trace entry point during migration."""
    with tracing() as trace:
        record(
            PassTrace(
                name="cull",
                input_ids=("first",),
                kept_ids=("first",),
                rejected=(),
                unresolved=(),
                duration_before=4.0,
                duration_after=4.0,
                provenance=_provenance(("first",)),
            )
        )

    assert trace.as_dict()["editorial_passes"][0]["name"] == "cull"


def test_editorial_pass_reports_duplicate_and_missing_fates() -> None:
    """A bad pass is visible rather than silently losing an editorial input."""
    trace = Trace()

    trace.record_editorial_pass(
        PassTrace(
            name="cull",
            input_ids=("kept-twice", "missing", "rejected"),
            kept_ids=("kept-twice",),
            rejected=(
                TraceDecision("kept-twice", "also rejected"),
                TraceDecision("rejected", "unusable exposure"),
            ),
            unresolved=(),
            duration_before=12.0,
            duration_after=4.0,
            provenance=_provenance(("kept-twice", "missing", "rejected")),
        )
    )

    payload = trace.as_dict()

    assert payload["editorial_passes"][0]["conservation"] == {
        "valid": False,
        "missing_ids": ["missing"],
        "duplicate_ids": ["kept-twice"],
        "unexpected_ids": [],
    }
    assert "!! conservation failure" in trace.report()


def test_editorial_report_marks_abbreviated_decisions_as_display_only() -> None:
    """Markdown samples long decisions while JSON keeps every named fate."""
    input_ids = tuple(f"reject-{number}" for number in range(13))
    trace = Trace()

    trace.record_editorial_pass(
        PassTrace(
            name="cull",
            input_ids=input_ids,
            kept_ids=(),
            rejected=tuple(
                TraceDecision(asset_id, f"reason {number}")
                for number, asset_id in enumerate(input_ids)
            ),
            unresolved=(),
            duration_before=52.0,
            duration_after=0.0,
            provenance=_provenance(input_ids),
        )
    )

    report = trace.report()
    payload = trace.as_dict()

    assert "showing 12 of 13; full list in JSON" in report
    assert "reject-12 — reason 12" not in report
    assert payload["editorial_passes"][0]["rejected"][-1] == {
        "asset_id": "reject-12",
        "reason": "reason 12",
    }


def test_a_candidate_with_no_score_is_not_described_as_scoring_zero() -> None:
    """Story-first candidates carry no score; the account must not invent a 0.00 for them."""
    from datetime import UTC, datetime

    from immich_memories.analysis.corpus.trace import _facts_of
    from tests.conftest import make_asset

    taken = datetime(2025, 7, 5, 7, 12, tzinfo=UTC)
    unscored = make_asset("a1", original_file_name="IMG_2438.jpg", file_created_at=taken)

    class Scored:
        clip = unscored
        score = 0.42

    assert "score" not in _facts_of(unscored)
    assert _facts_of(unscored).startswith("IMG_2438.jpg  2025-07-05")
    assert "score=0.42" in _facts_of(Scored())
