"""Each selection decision as a trace span: what went in, what came out, and why each clip left.

The selection trace already records every stage for the run's account; this sends the same
record to the collector as it is made, so a trace answers "why is that clip not in the film"
without the account file. A span is instantaneous (the work it summarises is timed by the
stage span around it) and carries one `clip.dropped` event per clip, up to a cap.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from immich_memories.tracking import otel

if TYPE_CHECKING:
    from immich_memories.analysis.corpus.records import PassTrace
    from immich_memories.analysis.corpus.trace import Stage

# A stage that drops a year's worth of clips names the first ones and counts the rest.
_CLIPS_PER_SPAN = 50
_REASONS_PER_SPAN = 20


def stage(recorded: Stage, clips: Mapping[str, str]) -> None:
    """A selection stage: its counts, its own reasons, and each clip it dropped."""
    span = otel.start(
        f"select {recorded.name}",
        {
            "selection.input": recorded.kept + recorded.dropped,
            "selection.kept": recorded.kept,
            "selection.dropped": recorded.dropped,
            "selection.favorites.in": recorded.favorites_in,
            "selection.favorites.out": recorded.favorites_out,
            "selection.reasons": recorded.reasons[:_REASONS_PER_SPAN] or None,
        },
    )
    for asset_id in recorded.lost_ids[:_CLIPS_PER_SPAN]:
        details = {
            "immich.asset.id": asset_id,
            "clip.reason": recorded.notes.get(asset_id),
            "clip.facts": clips.get(asset_id),
        }
        span.add_event(
            "clip.dropped", {key: value for key, value in details.items() if value is not None}
        )
    otel.end(span)


def editorial_pass(recorded: PassTrace) -> None:
    """An editorial pass: its counts, the model that judged, and each clip it rejected."""
    rejected = recorded.rejected + recorded.unresolved
    span = otel.start(
        f"select {recorded.name}",
        {
            "selection.input": len(recorded.input_ids),
            "selection.kept": len(recorded.kept_ids),
            "selection.dropped": len(rejected),
            "selection.unresolved": len(recorded.unresolved) or None,
            "selection.seconds.before": recorded.duration_before,
            "selection.seconds.after": recorded.duration_after,
            "gen_ai.request.model": recorded.provenance.model_identity or None,
            "selection.cache_hit": recorded.provenance.cache_hit,
        },
    )
    for decision in rejected[:_CLIPS_PER_SPAN]:
        span.add_event(
            "clip.dropped", {"immich.asset.id": decision.asset_id, "clip.reason": decision.reason}
        )
    if recorded.conservation is not None and not recorded.conservation.valid:
        otel.mark_failed(span, "ConservationFailure", "the pass did not give every clip one fate")
    otel.end(span)
