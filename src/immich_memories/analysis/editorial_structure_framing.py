"""Decisions the structure planner makes about what the film is of, before and around selection.

Whether a happening sits near home, which families a written subject's pool is narrowed to, the
memory-worthy tier a model or the rules reader gives each family (or a selected story's own
hierarchy leaves it at), and the slot/depth budget a product's target seconds buys: all of it
is read once from facts the planner already holds, never asked again mid-selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from immich_memories.analysis.editorial_block_votes import judge_worthiness, worth_criterion_v44
from immich_memories.analysis.editorial_episode_documents import factual_moment_rows
from immich_memories.analysis.editorial_home_radius import home_of, near_home_of
from immich_memories.analysis.editorial_picture_ladders import depth_cap
from immich_memories.analysis.editorial_structure_budget import (
    MIN_CARRIER_SECONDS,
    NOMINAL_STILL_SECONDS,
)
from immich_memories.analysis.editorial_structure_contract import StructurePlanningInput
from immich_memories.analysis.editorial_structure_material import Material, Wall, anchor_line
from immich_memories.store.vote_banks import VoteBank

SECONDS_PER_SLOT = NOMINAL_STILL_SECONDS
STORY_RANK = {"central": 0, "supporting": 1}


def near_home_test(source: StructurePlanningInput, wall: Wall):
    home = home_of(source.config.trips)

    def near_home(f):
        pts: list[tuple[float, Any]] = []
        for a in wall.event_assets.get(f, []):
            asset = source.assets.get(a)
            exif = asset.exif_info if asset is not None else None
            if not exif or exif.latitude is None:
                continue
            pts.append((exif.latitude, exif.longitude))
        return near_home_of(home, pts)

    return near_home


@dataclass
class SubjectPool:
    """A subject memory reads only the happenings the gate read as concerning the subject."""

    units: dict[str, list[dict]]
    moment_assets: dict[str, list[str]]
    rows_fn: Any
    record: dict | None = None


def subject_pool(marker, gate_tier, wall: Wall, material) -> SubjectPool:
    """The candidate pool comes first; the story is built on it alone. Every other product
    reads the whole period."""
    if not marker:
        return SubjectPool(material.units, material.moment_assets, factual_moment_rows)
    pool = {f for f, t in gate_tier.items() if t <= 1}
    pool_moments = {m for m, f in wall.family_of_moment.items() if f in pool}

    def pool_rows(tables_, aliases_):
        return [
            row
            for row in factual_moment_rows(tables_, aliases_)
            if row.get("moment_id") in pool_moments
        ]

    return SubjectPool(
        {f: units for f, units in material.units.items() if f in pool},
        {m: ids for m, ids in material.moment_assets.items() if m in pool_moments},
        pool_rows,
        {
            "criterion_marker": marker,
            "families_in_pool": len(pool),
            "families_total": len(gate_tier),
            "moments_in_pool": len(pool_moments),
        },
    )


def chapters_of(selection, carriers, anchor_label) -> list[dict]:
    """Chapters are the chosen episodes in the module's own order, so a carrier's
    1-based `chapter` indexes this list exactly as the default path's beats do."""
    episode_of = {e.key: e for e in selection.story.episodes}
    chapter_families: dict[str, list[str]] = {}
    for carrier in carriers:
        known = chapter_families.setdefault(carrier["story_episode"], [])
        if carrier["event"] not in known:
            known.append(carrier["event"])
    return [
        {
            "chapter": f"S{number:02d}",
            "beat": row["title"],
            "anchors": [anchor_label[f] for f in chapter_families.get(row["episode"], [])],
            "share": 0.0,
            "show": (episode_of[row["episode"]].significance or row["title"])
            if row["episode"] in episode_of
            else row["title"],
            "budget": row["granted"],
            "capacity": row["depicted_moments"],
            "families": list(chapter_families.get(row["episode"], [])),
        }
        for number, row in enumerate(selection.episodes, 1)
    ]


def story_worthiness(selection, wall: Wall, tier: dict, worth_reason: dict) -> None:
    """Worthiness comes from the story's own hierarchy, not a separate ballot."""
    for episode in selection.story.episodes:
        rank = STORY_RANK.get(episode.role, 2)
        for moment_alias in episode.moments:
            f = wall.family_of_moment.get(moment_alias)
            if f is not None and rank < tier.get(f, 3):
                tier[f] = rank
                worth_reason[f] = episode.title
    for f in wall.fam_ids:
        tier.setdefault(f, 2)


def evidence_partitions(intent, wall: Wall, tier: dict) -> set[str]:
    parts = set()
    for f in wall.fam_ids:
        if tier[f] > 1:
            continue
        day = datetime.fromisoformat(wall.moments[wall.families[f][0]]["taken"]).date()
        part = intent.partition_for(day)
        if part is not None:
            parts.add(part.key)
    return parts


def partition_cap(
    intent, target_seconds: float, prior, content_budget=None
) -> tuple[int, int, int | None]:
    """Slots, the per-anchor depth cap and the product's partition carrier limit."""
    slots_total = int(
        (target_seconds if content_budget is None else content_budget) // SECONDS_PER_SLOT
    )
    cap = (
        depth_cap(target_seconds)
        if content_budget is None
        else int(content_budget // MIN_CARRIER_SECONDS)
    )
    limit = intent.max_carriers_per_partition
    if limit is not None:
        cap = min(cap, limit)
    if limit is not None and prior:
        prior_counts: dict[str, int] = {}
        for c in prior["carriers"]:
            part = intent.partition_for(datetime.fromisoformat(c["taken"]).date())
            if part is not None:
                prior_counts[part.key] = prior_counts.get(part.key, 0) + 1
        if any(n > limit for n in prior_counts.values()):
            raise ValueError(
                "prior plan exceeds the product's partition carrier limit; replan without the incompatible prior"
            )
    return slots_total, cap, limit


def worthiness_gate(
    source, ports, wall: Wall, material: Material, *, admission, admission_key, record
):
    """Keep scoped admission; ordinary story importance comes from the story reading."""
    if ports.draft is not None:
        return ports.draft.tiers.copy(), ports.draft.reasons.copy(), ""
    if ports.rules is not None:
        tiers, reasons = ports.rules.worthiness(wall, near_home_test(source, wall))
        record("memory-worthy-gate", {"version": "rules-v1", "tiers": tiers, "reasons": reasons})
        return tiers, reasons, ""
    criterion, marker = worth_criterion_v44(source.case.product, source.intent.subject)
    if not marker:
        record("memory-worthy-gate", {"version": "story-importance-v1", "rounds": []})
        return {}, {}, ""
    bank = VoteBank(source.bank_store, "memory-worthy", source.case.key)
    gate_tier, gate_reason, gate_rounds = judge_worthiness(
        ports.judge,
        happenings=wall.fam_ids,
        label_of=wall.anchor_label,
        text_of=lambda f: anchor_line(wall, material, f).split(": ", 1)[-1],
        near_home=near_home_test(source, wall),
        contract=admission,
        contract_key=admission_key,
        criterion=criterion,
        marker=marker,
        period_label=source.case.label,
        bank=bank,
        save=bank.save,
    )
    record(
        "memory-worthy-gate",
        {
            "version": "memory-worthy-v2-contract",
            "counts": {
                "remarkable": sum(1 for t in gate_tier.values() if t == 0),
                "maybe": sum(1 for t in gate_tier.values() if t == 1),
                "background": sum(1 for t in gate_tier.values() if t == 2),
            },
            "tiers": {wall.anchor_label[f]: t for f, t in gate_tier.items()},
            "reasons": {wall.anchor_label[f]: r for f, r in gate_reason.items()},
            "rounds": gate_rounds,
        },
    )
    return gate_tier.copy(), gate_reason.copy(), marker
