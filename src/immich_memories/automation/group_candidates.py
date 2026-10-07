"""Propose a memory for each saved people group with content (#1500 slice 10).

A saved group (`people/groups.py`) is a label plus a `PersonExpression` over canonical
person ids. Discovery treats a group like `MultiPersonDetector`'s pairs: a multi_person
candidate whose people condition is the group's expression, so `GenerationRequest` emits
`--people-expression`, which resolves exactly as `generate --group <label>` would. A group
renamed or edited after discovery is read again at generate time, from the store, same as
any other saved reference.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from immich_memories.automation.candidates import (
    CandidateCategory,
    MemoryCandidate,
    make_memory_key,
)
from immich_memories.automation.closeness import group_weight
from immich_memories.config_loader import Config
from immich_memories.people.groups import SavedGroup


class GroupCandidateDetector:
    """Proposes a multi_person memory for each saved group that has content."""

    BASE_SCORE = 0.65

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list[Any],
        generated_keys: set[str],
        config: Config,
        today: date,
        groups: list[SavedGroup] | None = None,
        person_asset_counts: dict[str, int] | None = None,
        closeness: dict[str, float] | None = None,
    ) -> list[MemoryCandidate]:
        """Emit one candidate per saved group, skipping any with no pictures in last year.

        ``person_asset_counts`` is each member's count for that year, the one the film reads.
        """
        counts = person_asset_counts or {}
        year = today.year - 1
        start, end = date(year, 1, 1), date(year, 12, 31)

        candidates = []
        for group in groups or []:
            asset_count = sum(counts.get(leaf, 0) for leaf in group.expression.leaf_values)
            if counts and asset_count == 0:
                continue

            mem_key = make_memory_key(
                "multi_person",
                start,
                end,
                discriminator=f"group:{group.label}",
                person_expression=group.expression,
            )
            if mem_key in generated_keys:
                continue

            reason = f"Saved group '{group.label}'"
            if asset_count:
                reason += f", {asset_count} assets"

            candidates.append(
                MemoryCandidate(
                    memory_type="multi_person",
                    category=CandidateCategory.MULTI_PERSON,
                    date_range_start=start,
                    date_range_end=end,
                    person_names=[],
                    memory_key=mem_key,
                    score=round(
                        self.BASE_SCORE * group_weight(group.expression.leaf_values, closeness), 3
                    ),
                    reason=reason,
                    asset_count=asset_count,
                    extra_params={"person_expression": group.expression.to_dict()},
                )
            )
        return candidates
