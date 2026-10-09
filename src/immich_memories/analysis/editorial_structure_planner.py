"""Shared production structure planning over conserved factual inputs.

The algorithm is extracted intact from the validated matrix planner. File acquisition,
model transports, and lineage belong to adapters; this module owns editorial decisions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from functools import partial
from operator import itemgetter

from immich_memories.analysis import llm_metrics
from immich_memories.analysis.editorial_cut_invariants import check_finished_cut
from immich_memories.analysis.editorial_exposure_chains import chain_holds_for
from immich_memories.analysis.editorial_family_seat import FilmSeatSource, seat_in_film
from immich_memories.analysis.editorial_final_hash_review import (
    hash_repeat_relation,
    scene_pair_relation,
)
from immich_memories.analysis.editorial_owner_required import admit_owner_required
from immich_memories.analysis.editorial_people_condition_pool import (
    exclude_people_condition_violators,
    with_people_condition_exclusion,
)
from immich_memories.analysis.editorial_picture_admission import picture_admission, shows_life
from immich_memories.analysis.editorial_review_list import write_for_cut
from immich_memories.analysis.editorial_rule_banked_facts import (
    NO_BANKED_FACTS,
    BankedAnswers,
    banked_leaders,
    open_banked_facts,
)
from immich_memories.analysis.editorial_rule_quality import rule_representative_rank
from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_shareability import FAMILY, SHAREABLE
from immich_memories.analysis.editorial_shareability_tiers import audience_check_for
from immich_memories.analysis.editorial_story_candidates import story_candidates
from immich_memories.analysis.editorial_story_lookalike import hash_pair_relation
from immich_memories.analysis.editorial_story_planner import select_story_first
from immich_memories.analysis.editorial_story_replacement_pool import alternatives_pool
from immich_memories.analysis.editorial_story_replies import film_close_family
from immich_memories.analysis.editorial_story_trips import detect_film_trips
from immich_memories.analysis.editorial_structure_audience import (
    AudienceBank,
    AudienceGate,
)
from immich_memories.analysis.editorial_structure_budget import CONTENT_RESERVE_SECONDS, still_floor
from immich_memories.analysis.editorial_structure_contract import (
    RulesDraft,
    StructurePlannerPorts,
    StructurePlanningInput,
    StructurePlanningResult,
)
from immich_memories.analysis.editorial_structure_finishing import (
    PlanRun,
    admit_retained_originals,
    announce_count,
    apply_audience_gate,
    drop_filler_nothing_vouches_for,
    final_duplicate_review,
    frame_quality_of,
    replacement_offers,
    resolve_motion_and_timing,
    seat_again_after_review,
    trim_to_timing,
)
from immich_memories.analysis.editorial_structure_framing import (
    SECONDS_PER_SLOT,
    SubjectPool,
    chapters_of,
    near_home_test,
    partition_cap,
    story_worthiness,
    subject_pool,
    worthiness_gate,
)
from immich_memories.analysis.editorial_structure_framing import (
    evidence_partitions as evidence_partitions_of,
)
from immich_memories.analysis.editorial_structure_lines import strangers_only
from immich_memories.analysis.editorial_structure_material import (
    Material,
    Wall,
    build_material,
    hold_the_ends,
    read_wall,
    refresh_candidates,
)
from immich_memories.analysis.editorial_structure_record import (
    PlanFacts,
    PlanOutcome,
    build_result,
    contract_texts,
    merged_threads_log,
    provider_metrics,
    shave_content_duration,
)
from immich_memories.analysis.editorial_thin_step import polish_the_draft
from immich_memories.analysis.editorial_unvouched_filler import (
    filler_evidence,
    owner_vouches_for,
)
from immich_memories.analysis.subject_framing import framing_visibility
from immich_memories.config_tiers import nas_draft_config
from immich_memories.photos.burst_dedup import BurstDeduplicator
from immich_memories.processing.editorial_timing import bind_editorial_timeline
from immich_memories.security import write_secret_file
from immich_memories.tracking.timed import timed

logger = logging.getLogger(__name__)

FLAGGED_LINE = re.compile(r"nsfw=yes|exposure=(partial|nude)")


@timed("selection.structure")
def plan_structure(
    source: StructurePlanningInput, ports: StructurePlannerPorts
) -> StructurePlanningResult:
    """Run the shared editorial algorithm on an already captured production wall."""
    bursts = ports.burst_deduplicator or BurstDeduplicator()
    ports = replace(ports, burst_deduplicator=bursts)
    if ports.refine is not None:
        nas = replace(
            source,
            config=nas_draft_config(source.config),
            artifact_dir=source.artifact_dir / "nas-draft",
            # Only the refinement reads the captions a shareable clearance rests on. Judged by
            # the draft's rules, a picture nothing has described yet could never be cleared,
            # and an empty draft would end the film before any caption was read (#2135).
            # The refinement still gates every shot at the film's own level.
            audience=FAMILY if source.audience == SHAREABLE else source.audience,
        )
        # The reader must see the same narrowed pool `_plan_structure(nas, rules)` is
        # about to plan over (#1954): built from the un-narrowed `nas`, it could have
        # named a story or episode after a picture the people condition excludes.
        rules = replace(
            ports,
            judge=NoModelJudge(),
            rules=RuleStructureReader(
                exclude_people_condition_violators(nas).source, printed=ports.printed_near
            ),
            thin=None,
            laya=None,
            observe_story_motion=None,
            story_motion_metrics=None,
            refine=None,
            prepare_candidates=None,
            draft=None,
            live_source_integrity=None,
        )
        drafted = _plan_structure(nas, rules)
        drafted.write(nas.artifact_dir)
        assert drafted.draft is not None
        if not drafted.draft.carriers or drafted.plan.get("status") == "planning_incomplete":
            return drafted
        source, ports = ports.refine(source, drafted.draft)
        ports = replace(ports, burst_deduplicator=bursts)
    result = _plan_structure(source, ports)
    duration = result.plan.get("duration_realization") or {}
    if duration.get("status") in {"editorial_shortfall", "search_limited"}:
        logger.info(
            "%d distinct shots, final cut contains %.1f s of %.1f s available for content",
            len(result.plan["carriers"]),
            duration["selected_content_seconds"],
            duration["content_budget_seconds"],
        )
    return result


def _plan_structure(
    source: StructurePlanningInput, ports: StructurePlannerPorts
) -> StructurePlanningResult:
    """Apply the people condition to the whole pool once, then plan it in a single pass.

    `editorial_people_condition_pool.py` narrows `moment_asset_ids` before any budget or
    selection work runs, so every derived field (moment counts, budgets, the certified
    render timing) is already consistent with it (#1954, #1969): never a second pass, and
    never a rewrite of an already-planned carriers list.
    """
    narrowed = exclude_people_condition_violators(source)
    source = narrowed.source
    source.bank_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    source.artifact_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    audit_dir = source.artifact_dir / "derived-decisions"
    audit_dir.mkdir(mode=0o700, exist_ok=True)
    # Only the exact text gateway can reuse semantic answers across runs. These parsed
    # dictionaries memoize within this run and are written solely for audit/restart evidence.
    contract, contract_key, admission, admission_key = contract_texts(source.case, source.intent)
    wall = read_wall(source)
    material = build_material(source, ports, wall)
    # `source.assets` is already narrowed to non-violators above, so every reader of it
    # (this budget, the second one inside `_select`, chain holds, the rules reader) sees
    # the same pool without a second filter here.
    selection_budget = (
        source.render_timing.selection_budget(source.assets) if source.render_timing else None
    )
    slots_total, cap, partition_limit = partition_cap(
        source.intent, source.case.target_seconds, source.prior_plan, selection_budget
    )
    prior_assets = (
        {c["asset_id"] for c in source.prior_plan["carriers"]} if source.prior_plan else set()
    )
    run = PlanRun(
        final_content_cap=source.case.target_seconds - CONTENT_RESERVE_SECONDS,
        bind_stitch=material.builder.measured_stitch,
        still_floor=still_floor(source.config.photos.duration),
    )
    reader = ports.laya.cache_identity if ports.laya else "rules"
    library = AudienceBank(
        source.bank_store, answerer=f"{source.config.editorial.preparation.tier}|{reader}"
    )
    with llm_metrics.collecting() as counters:
        try:
            outcome = _select(
                source,
                ports,
                wall,
                material,
                run,
                library,
                audit_dir=audit_dir,
                contract=contract,
                admission=admission,
                admission_key=admission_key,
                partition_limit=partition_limit,
                prior_assets=prior_assets,
            )
        finally:
            # The holds this cut cast reach the store in one batch, even when the cut fails.
            library.flush()
    metrics = provider_metrics(counters)
    if run.render_timeline is None:
        run.shaved += shave_content_duration(
            run.carriers, run.final_content_cap, floor_for_stills=run.still_floor
        )
    elif sum(c["seconds"] for c in run.carriers) > run.final_content_cap:
        raise ValueError("Certified editorial content grew after its timing was fixed")
    outcome.metrics = metrics
    outcome.shaved = run.shaved
    outcome.content_cap = run.final_content_cap
    outcome.timing_binding = _timing_binding(source, run)
    write_for_cut(source, run.carriers, outcome.share_log.get("verdicts", {}))
    facts = PlanFacts(
        label=source.case.label,
        target_seconds=source.case.target_seconds,
        contract_key=contract_key,
        wall_sha256=hashlib.sha256(source.wall_bytes).hexdigest(),
        slots_total=slots_total,
        cap=cap,
        source_assets=narrowed.pool_size,
        fam_ids=wall.fam_ids,
        anchor_label=wall.anchor_label,
        period_people=wall.period_people,
        merge_log=wall.merge_log,
        document_sources=material.document_sources,
        document_excluded=material.builder.document_excluded,
        ineligible=material.ineligible,
        prior=source.prior_plan,
        prior_assets=prior_assets,
        prior_plan_ref=source.prior_plan_ref,
    )
    result = replace(
        build_result(source, ports, facts, outcome),
        draft=RulesDraft(
            outcome.selection,
            outcome.carriers,
            outcome.cut_carriers,
            outcome.tier,
            outcome.worth_reason,
            tuple(deepcopy(outcome.final_duplicates.get("collapsed_favourites", ()))),
        ),
    )
    if narrowed.excluded:
        result = with_people_condition_exclusion(result, narrowed.excluded)
    return result


def _timing_binding(source: StructurePlanningInput, run: PlanRun) -> dict:
    if run.render_timeline is None:
        return {}
    if source.render_timing is None:
        raise ValueError("Certified timeline lacks its source timing policy")
    return {
        "render_timing": bind_editorial_timeline(
            source.render_timing,
            run.render_timeline,
            [c["asset_id"] for c in run.carriers],
        )
    }


def _select(
    source: StructurePlanningInput,
    ports: StructurePlannerPorts,
    wall: Wall,
    material: Material,
    run: PlanRun,
    library: AudienceBank,
    *,
    audit_dir,
    contract: str,
    admission: str,
    admission_key: str,
    partition_limit: int | None,
    prior_assets: set[str],
) -> PlanOutcome:
    """The whole selection under one metrics collector: gate, story, audience, duplicates."""

    def record_story(name: str, payload) -> None:
        write_secret_file(
            audit_dir / f"{name}.private.json",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )

    audience_tier = source.config.editorial.preparation.tier
    chains = chain_holds_for(source.assets, source.audience_annotations, source.companion_detectors)

    gate = AudienceGate(
        ports.judge,
        audience=source.audience,
        annotations=source.audience_annotations,
        flag_rows=source.shareability_flags,
        lines=source.annotations,
        bank_path=audit_dir / "shareability.private.json",
        library=library,
        check_audience=audience_check_for(
            audience_tier,
            strict_sharing=source.config.editorial.strict_sharing and source.audience == SHAREABLE,
            local_reader=ports.laya is not None,
        ),
        chains=chains,
        companion_heads=source.companion_detectors,
        activity_reader=ports.laya.activity_answers if ports.laya else None,
        prepare_candidates=partial(refresh_candidates, source, ports, material, chains)
        if ports.prepare_candidates
        else None,
        ocr_text_of=ports.document_ocr_text,
        protected=source.owner_required_asset_ids,
    )
    tier, worth_reason, marker = worthiness_gate(
        source,
        ports,
        wall,
        material,
        admission=admission,
        admission_key=admission_key,
        record=record_story,
    )
    pool = subject_pool(marker, tier, wall, material)
    if pool.record is not None:
        record_story("subject-pool", pool.record)
    # A no-model draft asks nothing, so it reads the model's answers through `banked` alone.
    banked = _banked_facts(source, ports)
    if ports.rules is not None:
        record_story("banked-facts", banked.record())
    selection = _story_selection(
        source,
        ports,
        wall,
        material,
        pool,
        gate,
        contract=contract,
        tier=tier,
        marker=marker,
        record=record_story,
        partition_limit=partition_limit,
        banked=banked,
        looks_alike=hash_pair_relation(ports.thumbnail_hash),
        scene_alike=scene_pair_relation(ports.scene_print) if ports.scene_print else None,
        capacity_hash_alike=hash_repeat_relation(ports.thumbnail_hash),
    )
    run.carriers = list(selection.carriers)
    gates = picture_admission(source, ports, material, selection, gate)
    if ports.draft is not None:
        run.cut_carriers.extend(deepcopy(ports.draft.removed))
        run.final_duplicates["collapsed_favourites"] = deepcopy(ports.draft.collapsed_favourites)
    if ports.thin is not None:
        run.carriers = polish_the_draft(
            source,
            ports,
            material,
            wall,
            selection,
            pool,
            gate,
            run.carriers,
            run,
            contract=contract,
            record=record_story,
            gates=gates,
        )
    seat = partial(
        seat_in_film,
        film=FilmSeatSource(source, ports.rules, selection, material.units, banked),
        candidates_of=story_candidates(selection, wall, pool, material.units),
        admission=gates,
        excluded=material.document_sources,
    )
    run.carriers = seat(run.carriers, record=record_story)
    required = frozenset(source.owner_required_asset_ids)
    if required:
        # After the read, never before it: the owner's ticks change no prompt.
        run.carriers, owner_record = admit_owner_required(
            run.carriers,
            required=source.owner_required_asset_ids,
            units=material.units,
            stories=selection.story.stories,
            episodes=selection.story.episodes,
            anchor_label=wall.anchor_label,
            line_of=lambda asset_id: material.story_lines.get(asset_id, ""),
        )
        record_story("owner-required", owner_record)
    trim_to_timing(run, source, record_story, protected=required)
    # The film is settled here, so its ends are known. The shave that follows takes the half
    # second back when the target leaves no room for it. An opening and a closing frame are
    # read rather than glanced at whoever cut them, so this is not the no-model reader's.
    if ports.draft is None:
        hold_the_ends(run.carriers, nominal=source.config.photos.duration)
    chapters = chapters_of(selection, run.carriers, wall.anchor_label)
    beats = [row["beat"] for row in chapters]
    story_worthiness(selection, wall, tier, worth_reason)
    evidence_partitions = evidence_partitions_of(source.intent, wall, tier)
    carriers_at_selection = len(run.carriers)
    run.carriers.sort(key=itemgetter("taken"))
    run.selection_stages = {
        "funded_picture_requests": 0,
        "after_funded_acquisition": len(run.carriers),
        "before_shareability": len(run.carriers),
    }
    announce_count(len(run.carriers), "going into the family-viewing check")
    share_log = apply_audience_gate(
        run,
        gate,
        selection,
        material,
        wall,
        admits=lambda row, cut: gates.admits(row, cut=cut, tier_of={}) is None,
    )
    if required - {c["asset_id"] for c in run.carriers}:
        # The safety gate keeps its authority over an owner tick; say so where the owner can read it.
        record_story(
            "owner-required-after-audience",
            {"removed": sorted(required - {c["asset_id"] for c in run.carriers})},
        )
    resolve_motion_and_timing(run, source, ports)
    # The review protects the same people the seat counts: in a person film, the subject's own.
    close_of = film_close_family(source)
    # Only the final duplicate review reaches past a carrier's own moment and story: the
    # audience gate's own replacement (`apply_audience_gate`, above) drops rather than widen
    # its search, per `editorial_shareability.apply_gate`'s own contract.
    partition_of_taken = (
        (
            lambda taken: (
                part.key
                if (part := source.intent.partition_for(datetime.fromisoformat(taken).date()))
                else None
            )
        )
        if partition_limit is not None
        else None
    )
    final_duplicate_review(
        run,
        ports,
        replacements_for=replacement_offers(
            alternatives_pool(
                selection,
                material.units,
                wall.anchor_label,
                include_elsewhere=True,
                partition_of=partition_of_taken,
                cut_carriers=run.carriers,
            )
        ),
        prior=source.prior_plan,
        prior_assets=prior_assets,
        owner_required=source.owner_required_asset_ids,
        close_family_of=lambda asset_id: close_of(selection.lines.get(asset_id, "")),
        admits=lambda row, cut: gates.admits(row, cut=cut, tier_of={}) is None,
        frame_quality=frame_quality_of(source),
        requested_seconds=source.case.target_seconds,
    )
    run.selection_stages["after_final_duplicate_review"] = len(run.carriers)
    announce_count(len(run.carriers), "after the duplicate review")
    if ports.rules is not None:
        # The last removal pass, so no replacement pass can bring a removed filler's like back in.
        # A polished film runs it too: the polish refines the no-model film, and must not keep
        # a screen or an empty frame that film would have dropped.
        drop_filler_nothing_vouches_for(run, filler_evidence(source), record_story)
    # After every pass that removes a shot, so none of them can undo a family seat. It seats a
    # close family member's frame, never filler the pass above removed.
    seat_again_after_review(
        run,
        ports,
        seat=lambda cut: seat(
            cut,
            record=lambda _name, audit: record_story("family-seat-after-review", audit),
        ),
    )
    record_story("picture-admission", {"checks": gates.decisions})
    admit_retained_originals(run, source, material.builder)
    check_finished_cut(source, selection, material, run, gate, banked, share_log, record_story)
    return PlanOutcome(
        contract=contract,
        carriers=run.carriers,
        cut_carriers=run.cut_carriers,
        selection=selection,
        chapters=chapters,
        beats=beats,
        threads=merged_threads_log(beats, selection.story.thesis),
        tier=tier,
        worth_reason=worth_reason,
        share_log=share_log,
        final_duplicates=run.final_duplicates,
        motion_metrics=run.motion_metrics,
        selection_stages=run.selection_stages,
        evidence_partitions=evidence_partitions,
        calls=ports.judge.calls,
        ladder_reads=0,
        carriers_at_selection=carriers_at_selection,
    )


def _story_selection(
    source,
    ports,
    wall: Wall,
    material: Material,
    pool: SubjectPool,
    gate: AudienceGate,
    *,
    contract: str,
    tier: dict,
    marker: str,
    record,
    partition_limit: int | None,
    banked: BankedAnswers,
    looks_alike=None,
    scene_alike=None,
    capacity_hash_alike=None,
):
    if ports.draft is not None:
        carriers = deepcopy(ports.draft.carriers)
        # Refinement edits a finished cut. Its measured intervals belong to the old
        # playback decisions; finishing binds fresh intervals after those decisions.
        for carrier in carriers:
            for field in ("start_time", "end_time", "render_frame_seconds"):
                carrier.pop(field, None)
        return replace(
            deepcopy(ports.draft.selection),
            lines=source.annotations,
            carriers=[material.builder.refresh_clip_facts(carrier) for carrier in carriers],
        )
    unit_of = {u["asset_id"]: u for units in material.units.values() for u in units}
    durations = [u["seconds"] for units in pool.units.values() for u in units if u["seconds"] > 0]
    seconds_per_slot = sum(durations) / len(durations) if durations else SECONDS_PER_SLOT
    pool_assets = {a for ids in pool.moment_assets.values() for a in ids if a in source.assets}
    trips = detect_film_trips(
        (source.assets[a] for a in sorted(pool_assets)),
        source.config.trips,
        journey=source.case.product == "trip",
    )
    close_family = film_close_family(source)
    return select_story_first(
        judge=ports.judge,
        rules=ports.rules,
        tables=wall.tables,
        aliases=wall.aliases,
        factual_rows_fn=pool.rows_fn,
        moment_assets=pool.moment_assets,
        lines=material.story_lines,
        flagged=lambda asset_id: bool(FLAGGED_LINE.search(source.annotations.get(asset_id, ""))),
        subject=lambda asset_id: framing_visibility(source.annotations.get(asset_id, "")),
        # With no model to compare pictures, a capture group's frame is won on capture facts,
        # and on whatever a model already said about them on an earlier run.
        representative_rank=rule_representative_rank(
            source.assets,
            source.annotations,
            source.motion_residuals,
            leads=banked_leaders(banked, tuple(source.episode_readings)),
        )
        if ports.rules is not None
        else None,
        life=lambda asset_id: shows_life(material, unit_of, asset_id),
        full_lines=source.annotations,
        contract=contract + "\n\n" + source.intent.story_prompt_block(),
        event_units=pool.units,
        family_of_moment=wall.family_of_moment,
        anchor_label=wall.anchor_label,
        description_of=material.text.description,
        quality=material.builder.quality,
        motion_line=ports.observe_story_motion,
        episode_readings=source.episode_readings,
        target_seconds=(
            source.render_timing.selection_budget(
                source.assets, expected_clip_duration=seconds_per_slot
            )
            if source.render_timing
            else source.case.target_seconds
        ),
        seconds_per_slot=seconds_per_slot,
        record=record,
        family_tier=tier,
        standing=(ports.rules or RuleStructureReader(source)).standing,
        excluded=material.document_sources,
        allow_story_gaps=bool(marker),  # a subject memory's stages span weeks with gaps
        journey=source.case.product == "trip",
        partition_limit=partition_limit,
        voice_per_partition=source.intent.voice_per_partition,
        context_without_life=source.intent.context_without_life,
        pool_is_subject=source.intent.pool_is_subject,
        occurrence_is_subject=source.intent.occurrence_is_subject,
        partition_of=lambda taken: (
            part.key
            if (part := source.intent.partition_for(datetime.fromisoformat(taken).date()))
            else None
        ),
        trips=trips,
        looks_alike=looks_alike,
        scene_alike=scene_alike,
        capacity_hash_alike=capacity_hash_alike,
        strangers_only=strangers_only(source.assets, source.audience_annotations),
        vouched=partial(owner_vouches_for, evidence=filler_evidence(source)),
        film_span=(source.case.ranges[0].start.date(), source.case.ranges[-1].end.date()),
        near_home=near_home_test(source, wall),
        banked=banked,
        close_family_of=lambda asset_id: close_family(source.annotations.get(asset_id, "")),
    )


def _banked_facts(source, ports) -> BankedAnswers:
    """What earlier model answers about this library say, for the draft that asks nothing.

    Only the no-model draft reads them. A model run asks its own questions about every
    candidate and banks the replies; handing it the same answers twice would change nothing
    and hide which run paid for what.
    """
    if ports.rules is None:
        return NO_BANKED_FACTS
    return open_banked_facts(
        attempts_dir=source.artifact_dir.parent,
        store=source.bank_store,
        audience=source.audience,
        episode_cards=source.episode_readings,
        own_producers=frozenset(
            str(row.get("producer_key", ""))
            for row in (source.lineage.get("episode_readings") or ())
        ),
    )
