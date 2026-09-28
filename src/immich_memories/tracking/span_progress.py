"""Read-back arithmetic shared by run reports and live progress."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from immich_memories.tracking.timing import Span


def uncovered_seconds(spans: Sequence[Span], wall_seconds: float) -> float:
    """Union measured operations; overlap and the run's enclosing span earn no extra credit."""
    intervals = sorted(
        (span.start, span.start + span.duration) for span in spans if span.name != "run"
    )
    covered = 0.0
    end = float("-inf")
    for start, stop in intervals:
        covered += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return max(0.0, wall_seconds - covered)


@dataclass(frozen=True)
class Estimate:
    fraction: float
    remaining_seconds: float


class SpanPlan:
    def __init__(self, spans: Sequence[Span], *, items: int | None = None) -> None:
        self.weights: dict[str, float] = {}
        for span in sorted(spans, key=lambda value: value.start):
            weight = span.duration * items / span.items if items and span.items else span.duration
            self.weights[span.name] = self.weights.get(span.name, 0.0) + weight

    def estimate(
        self,
        name: str,
        *,
        fraction: float | None,
        remaining: float | None = None,
    ) -> Estimate | None:
        """Scale future picture stages; let the current stage's measured ETA win."""
        if name not in self.weights or fraction is None:
            return None
        names = list(self.weights)
        index = names.index(name)
        done = sum(self.weights[key] for key in names[:index])
        current = self.weights[name]
        fraction = min(1.0, max(0.0, fraction))
        done += current * fraction
        left = current * (1 - fraction) if remaining is None else max(0.0, remaining)
        left += sum(self.weights[key] for key in names[index + 1 :])
        return Estimate(done / (done + left) if done + left else 1.0, left)


def span_tree(spans: Sequence[Span], wall_seconds: float) -> list[str]:
    """A stable, plain-text tree, with normalized rates and the unmeasured remainder."""
    by_id = {span.span_id: span for span in spans}
    rows = []
    for span in sorted(spans, key=lambda value: value.span_id):
        ancestors: set[int] = set()
        parent = span.parent_id
        while parent in by_id and parent not in ancestors:
            ancestors.add(parent)
            parent = by_id[parent].parent_id
        rate = f", {span.duration / span.items:.4f} s/item ({span.items})" if span.items else ""
        error = f" [{span.error['type']}]" if span.error else ""
        rows.append(f"{'  ' * len(ancestors)}{span.name}: {span.duration:.3f} s{rate}{error}")
    uncovered = uncovered_seconds(spans, wall_seconds)
    fraction = uncovered / wall_seconds if wall_seconds else 0
    rows.append(f"Uncovered: {uncovered:.3f} s ({fraction:.1%} of wall time)")
    return rows
