"""A hermetic stand-in for the story-first editorial route.

The launch smoke runs the real web server against the fake Immich service in
``fake_immich.py``. The sole production selector needs two things a hermetic
launch cannot have: a text model to read the period with, and an annotation
store already prepared for this library. This module supplies exactly what
those two boundaries produce -- a durable attempt tree on disk, written through
the real ``EditorialAttempt`` so its lease and status file behave as they do in
production, and one ``(candidates, PipelineResult)`` pair -- so everything
downstream of selection (the cut job's progress, the review page, the pool
page, and the real FFmpeg render) runs against unmodified production code.

The one editorial decision is scripted in ``fake_library``: a picture ships when
the library hangs it on a story, every other picture is left out with the reason
written there, and a picture the owner ticks is admitted under the story nearest
in time. The kept pictures play in capture order, each held for the duration its
own metadata allows.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from immich_memories.security import write_secret_file
from tests.e2e import fake_library

# Both accounts' pictures: a film that names the partner account ships the partner's too.
from tests.e2e.fake_library import ACCOUNTS_BY_ID as BY_ID
from tests.e2e.fake_library import ACCOUNTS_STORY_OF as STORY_OF
from tests.e2e.fake_library import CARRIERS, DROPPED, LIBRARY, STORIES, THESIS
from tests.e2e.fake_live_motion import companions_of, live_projection

# The per-asset pass the real route runs before its named stages, and the one a
# first cut over a big library sits inside for a long time. It is scripted here
# so the Memory page's live detail -- the bar and the strip of pictures -- is
# exercised by the same file the production pass writes.
PREVIEW_STAGE = "previews"

# The exact labels `RuntimeEditorialPlanner` reports through `on_stage`, in the
# order the real route reaches them. The Memory page shows the current one, so a
# wrong label here would hide a real regression in the progress surface.
STAGES = (
    "Reading dates, places and people",
    "Reading event evidence",
    "Building editorial cards",
    "Editing the memory",
    "Validating selected source timing",
)

# Long enough that a reload lands on a running cut, short enough that the whole
# scripted selection stays well under the launch smoke's budget.
DEFAULT_STAGE_SECONDS = 0.15

# A real run of one memory type, recorded once by `scripts/record_demo_runs.py`. Naming one
# replays its cut instead of the script: the docs and demos then show what the product chose,
# and nothing has to run a model to show it again.
RECORDINGS = Path(__file__).parent / "fixtures" / "recordings"
RECORDING_ENV = "IMMICH_MEMORIES_FAKE_RECORDING"


def recording() -> dict[str, Any] | None:
    """The recording `IMMICH_MEMORIES_FAKE_RECORDING` names, or None for the scripted cut."""
    name = os.environ.get(RECORDING_ENV, "")
    if not name:
        return None
    folder = RECORDINGS / name
    if not (folder / "plan.json").is_file():
        raise RuntimeError(f"{RECORDING_ENV}={name!r}: no recording under {RECORDINGS}")
    return {path.stem: json.loads(path.read_text()) for path in folder.glob("*.json")}


def _replay(
    sources: Sequence[Any], recorded: dict[str, Any]
) -> tuple[list[Any], list[tuple[str, str]]]:
    """The recorded cut over these sources: its pictures in its order, every other one with
    the reason the recorded run gave it."""
    order = {
        asset_id: n for n, asset_id in enumerate(recorded["render-projection"]["selected_ids"])
    }
    reasons = {
        row["asset_id"]: row["reason"]
        for step in recorded["selection-trace"]["editorial_passes"]
        for row in step.get("rejected", ())
    }
    kept = sorted(
        (s for s in sources if _asset_of(s).id in order), key=lambda s: order[_asset_of(s).id]
    )
    dropped = [
        (asset_id, reasons.get(asset_id, "not in the recorded cut"))
        for asset_id in (_asset_of(s).id for s in sources)
        if asset_id not in order
    ]
    return kept, dropped


def _replayed_candidates(kept: Sequence[Any], recorded: dict[str, Any], *, photo_seconds: float):
    """The recorded cut's rows, each played over the interval the recorded run gave it."""
    intervals = recorded["render-projection"]["intervals"]
    by_id = {row.clip.asset.id: row for row in _candidates(kept, photo_seconds=photo_seconds)}
    rows = []
    for source in kept:
        row = by_id[_asset_of(source).id]
        start, end = intervals.get(row.clip.asset.id, (row.start_time, row.end_time))
        rows.append(replace(row, start_time=float(start), end_time=float(end)))
    return tuple(rows)


def write_recorded_plan(
    attempt_dir: Path, recorded: dict[str, Any], render_timing: dict | None
) -> None:
    """Leave the recorded run's own plan and decision log in this attempt."""
    plan = dict(recorded["plan"])
    if render_timing:
        plan["render_timing"] = render_timing
    write_secret_file(
        attempt_dir / "plan.private.json", json.dumps(plan, ensure_ascii=False, indent=2)
    )
    write_secret_file(
        attempt_dir / "selection-trace.private.json",
        json.dumps(recorded["selection-trace"], indent=2),
    )


# Both from the production carrier vocabulary: motion is capped, a still is held.
_MOTION_CAP_SECONDS = 6.0

_ACCEPTED_SHORTFALL_FRACTION = 0.15

_THESIS = THESIS

# Three weighed stories over the same period: one carries the memory, one
# supports it, one is texture. The weights are the output vocabulary.
_EPISODES = tuple(
    {
        "key": story.key,
        "title": story.title,
        "weight": story.weight,
        "role": story.role,
        "purpose": story.purpose,
    }
    for story in STORIES
    if any(picture.story_key == story.key for picture in CARRIERS)
)


def _asset_of(source: Any) -> Any:
    from immich_memories.api.models import VideoClipInfo

    return source.asset if isinstance(source, VideoClipInfo) else source


# Fixture id -> the id the server gave that picture, for every picture read from a real Immich.
_SERVER_IDS: dict[str, str] = {}
_BY_FILENAME = {picture.filename: picture for picture in fake_library.ACCOUNTS_BY_ID.values()}


def _adopt_server_ids(sources: Sequence[Any]) -> None:
    """Name the fixture pictures by the ids the server they were read from gave them.

    The fake Immich serves each picture under its fixture id. A real Immich seeded with the
    same library (the real-Immich feature pass) gives every upload an id of its own and keeps
    its file name, which is unique across the library: the script follows the file name.
    """
    global BY_ID, STORY_OF, CARRIERS, DROPPED, LIBRARY  # noqa: PLW0603 -- the script's own tables
    found = {
        _BY_FILENAME[asset.original_file_name].asset_id: asset.id
        for asset in map(_asset_of, sources)
        if asset.id not in BY_ID and asset.original_file_name in _BY_FILENAME
    }
    if not found:
        return
    _SERVER_IDS.update(found)

    def server(fixture_id: str) -> str:
        return _SERVER_IDS.get(fixture_id, fixture_id)

    def moved(picture: Any) -> Any:
        return replace(picture, asset_id=server(picture.asset_id))

    BY_ID = {server(key): moved(p) for key, p in fake_library.ACCOUNTS_BY_ID.items()}
    STORY_OF = {server(key): story for key, story in fake_library.ACCOUNTS_STORY_OF.items()}
    DROPPED = {server(key): reason for key, reason in fake_library.DROPPED.items()}
    LIBRARY = tuple(moved(picture) for picture in fake_library.LIBRARY)
    CARRIERS = tuple(moved(picture) for picture in fake_library.CARRIERS)


def _carrier_rows(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    """One carrier per chosen source, in capture order, under the story it belongs to.

    The reason is the line the library itself wrote about that picture, prefixed
    with its story title the way the production writer prefixes one.
    """
    from immich_memories.api.models import AssetType

    rows = []
    for row in candidates:
        asset = row.clip.asset
        story = _story_for(asset.id)
        picture = BY_ID[asset.id]
        rows.append(
            {
                "asset_id": asset.id,
                "kind": "video" if asset.type == AssetType.VIDEO else "still",
                "seconds": round(row.end_time - row.start_time, 2),
                "taken": asset.file_created_at.isoformat(),
                "story_episode": story.key,
                "story_weight": story.weight,
                "story_role": story.role,
                "why": (
                    f"{story.title}: {picture.caption}"
                    if asset.id in STORY_OF
                    else f"{story.title}: kept by the owner: {picture.caption}"
                ),
                "standing": "remarkable" if picture.is_favorite else "maybe",
                "start_time": row.start_time,
                "end_time": row.end_time,
                "moment_alternatives": _siblings(picture),
            }
        )
    return rows


def _siblings(picture: Any) -> list[str]:
    """The other stills of the same scene the cut left out: the moment's recorded alternatives."""
    return [
        other.asset_id
        for other in LIBRARY
        if other.scene == picture.scene
        and other.asset_id != picture.asset_id
        and not other.shipped
        and not other.is_video
    ][:3]


def _story_for(asset_id: str) -> Any:
    """The story a picture belongs to, or the story of the carrier nearest in time."""
    if asset_id in STORY_OF:
        return STORY_OF[asset_id]
    taken = BY_ID[asset_id].taken_at
    nearest = min(CARRIERS, key=lambda picture: abs(_seconds(picture.taken_at) - _seconds(taken)))
    return STORY_OF[nearest.asset_id]


def _seconds(stamp: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _select(
    sources: Sequence[Any], required: Sequence[str], excluded: Sequence[str] = ()
) -> tuple[list[Any], list[tuple[str, str]]]:
    """Ship the story pictures and whatever the owner ticked; leave the rest out with a reason.

    A picture the owner excluded is left out whatever its story, as the real editor's source
    eligibility refuses it ("owner exclusion").
    """
    kept, dropped = [], []
    wanted = set(required)
    for source in sources:
        asset_id = _asset_of(source).id
        if asset_id in excluded:
            dropped.append((asset_id, "owner exclusion"))
        elif asset_id in STORY_OF or asset_id in wanted:
            kept.append(source)
        else:
            dropped.append(
                (asset_id, DROPPED.get(asset_id, "not part of any story the month tells"))
            )
    return kept, dropped


def _duration_realization(*, requested: float, budget: float, content: float, slots: int) -> dict:
    """The production shape, computed from this fixture's own numbers."""
    shortfall = round(max(0.0, budget - content), 2)
    tolerance = round(max(0.0, budget * _ACCEPTED_SHORTFALL_FRACTION), 2)
    return {
        "requested_seconds": requested,
        "content_budget_seconds": budget,
        "selected_content_seconds": content,
        "shortfall_seconds": shortfall,
        "near_target_tolerance_seconds": tolerance,
        "accepted_shortfall_fraction": _ACCEPTED_SHORTFALL_FRACTION,
        "requested_picture_slots": slots,
        "status": "near_target" if shortfall <= tolerance else "editorial_shortfall",
    }


def _intent_report(content: float) -> dict:
    return {
        "status": "ok",
        "requested_seconds": content,
        "usable_seconds": content,
        "shortfall_seconds": 0.0,
        "reason": None,
        "coverage": {episode["key"]: 0 for episode in _EPISODES},
        "violations": [],
    }


def _evidence_lines(carriers: Sequence[dict]) -> tuple[Any, ...]:
    """One rendered line per carrier, grouped into the story it was read under.

    The real reader keys an episode by the exact annotation lines of its members; the
    fixture has no annotation store, so it renders the same shape from its own metadata.
    """
    from immich_memories.analysis.editorial_evidence_provenance import EpisodeEvidenceLines

    by_episode: dict[str, list[tuple[str, str]]] = {episode["key"]: [] for episode in _EPISODES}
    for row in carriers:
        by_episode[row["story_episode"]].append(
            (row["asset_id"], f"{row['asset_id']} | {row['kind']} | {row['taken']}")
        )
    return tuple(
        EpisodeEvidenceLines(
            group_id=key,
            evidence_key=sha256(repr(lines).encode()).hexdigest(),
            lines=tuple(lines),
        )
        for key, lines in by_episode.items()
        if lines
    )


def write_plan_files(
    attempt_dir: Path,
    carriers: Sequence[dict],
    realization: dict,
    dropped: Sequence[tuple[str, str]] = (),
    render_timing: dict | None = None,
) -> None:
    """Leave behind what the structure record and the projection leave after a real run."""
    from immich_memories.analysis.editorial_evidence_provenance import AttemptEvidenceProvenance

    AttemptEvidenceProvenance().capture(_evidence_lines(carriers), directory=attempt_dir)
    content = round(sum(row["seconds"] for row in carriers), 2)
    write_secret_file(
        attempt_dir / "plan.private.json",
        json.dumps(
            {
                # The structure record spreads its timing binding over the plan
                # the same way, so a reader of this attempt sees the timeline the
                # renderer was certified against.
                **({"render_timing": render_timing} if render_timing else {}),
                "story": {"thesis": _THESIS, "episodes": list(_EPISODES)},
                "carriers": list(carriers),
                "content_seconds": content,
                "duration_realization": realization,
                "intent_report": _intent_report(content),
                "status": "selection-awaiting-owner-review-not-rendered",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    write_secret_file(
        attempt_dir / "selection-trace.private.json",
        json.dumps(_decision_log(carriers, dropped), indent=2),
    )
    write_secret_file(
        attempt_dir / "render-projection.private.json",
        json.dumps(
            {
                "format": "editorial-source-rendering-v1",
                "selected_ids": [row["asset_id"] for row in carriers],
                "adjustments": [],
                "allow_live_motion": True,
                "intervals": {
                    row["asset_id"]: [row["start_time"], row["end_time"]] for row in carriers
                },
            },
            indent=2,
        ),
    )


def _decision_log(carriers: Sequence[dict], dropped: Sequence[tuple[str, str]] = ()) -> dict:
    """The decision log a real run writes beside its plan, in the real `Trace` shape.

    One pass keeps the story pictures and records every other candidate as
    rejected with the library's reason, so `runs why` reads a hermetic run the
    way it reads a real one.
    """
    from immich_memories.analysis.editorial_contracts import (
        DecisionProvenance,
        PassTrace,
        TraceDecision,
    )
    from immich_memories.analysis.selection_trace import Trace

    ids = tuple(row["asset_id"] for row in carriers)
    rejected = tuple(TraceDecision(asset_id, reason) for asset_id, reason in dropped)
    trace = Trace()
    trace.clips = {row["asset_id"]: f"{row['kind']}, {row['taken'][:10]}" for row in carriers}
    trace.clips.update(
        {
            asset_id: f"{BY_ID[asset_id].kind}, {BY_ID[asset_id].taken_at[:10]}"
            for asset_id, _ in dropped
            if asset_id in BY_ID
        }
    )
    trace.editorial_passes.append(
        PassTrace(
            name="picture_review",
            input_ids=ids + tuple(asset_id for asset_id, _ in dropped),
            kept_ids=ids,
            rejected=rejected,
            unresolved=(),
            duration_before=float(sum(row["seconds"] for row in carriers)),
            duration_after=float(sum(row["seconds"] for row in carriers)),
            provenance=DecisionProvenance(  # noqa: S106 - pass names, not secrets
                pass_name="picture_review",  # noqa: S106
                pass_version="fixture",  # noqa: S106
                schema_version="fixture",
                model_identity="none",
                input_ids=ids,
                sheet_hashes=(),
                request_key="",
                cache_hit=False,
            ),
        )
    )
    return trace.as_dict()


def _candidates(sources: Sequence[Any], *, photo_seconds: float) -> tuple[Any, ...]:
    """Demand every requested source, timed from its own metadata, in capture order."""
    from immich_memories.analysis.smart_pipeline import ClipWithSegment
    from immich_memories.api.models import VideoClipInfo

    rows = []
    for source in sorted(
        sources, key=lambda item: (_asset_of(item).file_created_at, _asset_of(item).id)
    ):
        if isinstance(source, VideoClipInfo):
            clip = source
            seconds = round(min(float(source.duration_seconds or 0.0), _MOTION_CAP_SECONDS), 2)
        else:
            seconds = float(photo_seconds)
            clip = VideoClipInfo(
                asset=source,
                duration_seconds=seconds,
                width=source.width,
                height=source.height,
            )
        rows.append(
            ClipWithSegment(clip=clip, start_time=0.0, end_time=seconds, score=0.0, analyzed=False)
        )
    return tuple(rows)


class _FakeEditorialPipeline:
    """The pipeline surface the Memory page drives, with a scripted cut behind it."""

    def __init__(
        self,
        *,
        app_config: Any,
        context: Any,
        stage_seconds: float,
        client: Any = None,
        companions: Sequence[Any] = (),
    ) -> None:
        from immich_memories.analysis.progress import ProgressTracker

        self._app_config = app_config
        self._context = context
        # Where a kept Live Photo's companion clips are read from, to measure their motion.
        self._client = client
        self._companions = tuple(companions)
        self._stage_seconds = stage_seconds
        self.tracker = ProgressTracker()
        # Nothing was downloaded or looked at, and the pool page says so out loud.

    def _request(self, sources: Sequence[Any], include_live_photos: bool) -> dict[str, Any]:
        context = self._context
        return {
            "key": context.key,
            "product": context.product,
            "target_seconds": context.target_seconds,
            "audience": context.audience,
            "hemisphere": context.hemisphere,
            "date_ranges": [[r.start.isoformat(), r.end.isoformat()] for r in context.case_ranges],
            "requested_assets": [_asset_of(source).id for source in sources],
            "required_assets": list(getattr(context, "owner_required_asset_ids", ())),
            "include_live_photos": include_live_photos,
            "hdr_only": False,
        }

    def run_editorial_source(
        self,
        sources: Sequence[Any],
        progress_callback: Any = None,
        *,
        include_live_photos: bool = True,
    ) -> tuple[list[Any], Any]:
        """Keep a real attempt, announce the real stages, return the real result shape.

        A kept Live Photo plays as motion when its measured clip earns it, and only while
        ``include_live_photos`` admits motion (`fake_live_motion`).
        """
        from immich_memories.analysis.editorial_projection import EditorialStageReporter
        from immich_memories.operations.cancellation import (
            PipelineCancelled,
            cancellation_scope,
            check_cancelled,
        )
        from immich_memories.operations.cut_progress import ANALYSIS_PHASE, StageUpdate
        from immich_memories.operations.editorial_attempt import EditorialAttempt

        _adopt_server_ids(sources)
        report_stage = EditorialStageReporter(self.tracker, progress_callback)
        self.tracker.start()
        request = self._request(sources, include_live_photos)
        try:
            with (
                EditorialAttempt(self._context.artifact_dir, request=request) as attempt,
                cancellation_scope(report_stage.repeat),
            ):
                from immich_memories.analysis.editorial_source_snapshot import (
                    SNAPSHOT_NAME,
                    source_payload,
                )
                from immich_memories.security import write_secret_file

                # The production route records the pool it read, and who the memory is about;
                # the pool page reads both back (`AttemptSourceSnapshots.capture`).
                context = self._context
                payload = source_payload(
                    list(sources), person_expression=getattr(context, "person_expression", None)
                ) | {
                    "people": list(getattr(context, "people", ())),
                    "person_match": getattr(context, "person_match", "and"),
                }
                write_secret_file(
                    attempt.directory / SNAPSHOT_NAME, json.dumps(payload, default=str)
                )
                self._prepare_previews(sources, attempt, report_stage, check_cancelled)
                for label in STAGES:
                    update = StageUpdate(
                        label, ANALYSIS_PHASE if label.startswith("Preparing") else "selection"
                    )
                    update = attempt.stage(update)
                    report_stage(update)
                    time.sleep(self._stage_seconds)
                    check_cancelled()
                recorded = recording()
                photo_seconds = self._app_config.photos.duration
                if recorded is not None:
                    kept, dropped = _replay(sources, recorded)
                    candidates = _replayed_candidates(kept, recorded, photo_seconds=photo_seconds)
                else:
                    kept, dropped = _select(
                        sources,
                        getattr(self._context, "owner_required_asset_ids", ()),
                        getattr(self._context, "owner_excluded_asset_ids", ()),
                    )
                    candidates = _candidates(kept, photo_seconds=photo_seconds)
                live = live_projection(
                    candidates,
                    sources,
                    config=self._app_config,
                    companions=self._companions,
                    fetch=lambda video_id: self._client.get_video_playback(video_id),
                    include_live_photos=include_live_photos,
                    demand=lambda extra: _candidates(extra, photo_seconds=photo_seconds),
                    content_budget=lambda carriers: self._content_budget(carriers, candidates),
                )
                selections = None
                if live is not None:
                    candidates, selections = live
                result = self._result(candidates, attempt.directory, len(sources), selections)
                realization = result.stats["editorial_duration_realization"]
                write_plan_files(
                    attempt.directory,
                    _carrier_rows(candidates),
                    realization,
                    dropped,
                    result.stats.get("editorial_render_timing"),
                )
                if recorded is not None:
                    # The projection above carries the recorded intervals; the plan and the
                    # decision log are the recorded run's own.
                    write_recorded_plan(
                        attempt.directory, recorded, result.stats.get("editorial_render_timing")
                    )
                if binding := result.stats.get("editorial_render_timing"):
                    from immich_memories.processing.render_inputs import write_render_inputs

                    # The production route keeps these beside the plan; so does the fixture.
                    write_render_inputs(
                        attempt.directory,
                        result.selected_clips,
                        result.editorial_selections,
                        result.clip_segments,
                        binding,
                    )
                attempt.complete(
                    selected=len(result.editorial_selections),
                    outcome="selected",
                    duration_realization=realization,
                )
                report_stage("Editorial selection complete", status="complete")
                with contextlib.suppress(Exception):
                    self.tracker.finish()
                return list(candidates), result
        except PipelineCancelled:
            with contextlib.suppress(PipelineCancelled):
                report_stage("Editorial selection cancelled", status="cancelled")
            raise

    def _prepare_previews(self, sources, attempt, report_stage, check_cancelled) -> None:
        """Walk the sources the way the real preparation pass does, publishing as it goes."""
        from immich_memories.operations.cut_progress import StageProgressWriter

        live = StageProgressWriter(lambda: attempt.directory)
        total = len(sources)
        # The whole pass takes about two stages whatever the pool size: long
        # enough that a watcher's one-second poll sees the bar move, short
        # enough that a library of a hundred pictures does not stall the smoke.
        pause = min(self._stage_seconds / 2, 2 * self._stage_seconds / max(total, 1))
        for index, source in enumerate(sources, 1):
            live.note_asset(_asset_of(source).id)
            update = live.publish(PREVIEW_STAGE, index, total)
            update = attempt.stage(update)
            report_stage(update)
            time.sleep(pause)
            check_cancelled()

    def _content_budget(self, carriers: list[dict], candidates: tuple[Any, ...]) -> float | None:
        """The render budget the run's timing policy gives these carriers, if it has one."""
        policy = self._context.render_timing
        if policy is None:
            return None
        assets = {row.clip.asset.id: row.clip.asset for row in candidates}
        rows = [{"asset_id": c["asset_id"], "seconds": c["seconds"]} for c in carriers]
        return float(policy.resolve(rows, assets).content_budget)

    def _result(
        self,
        candidates: tuple[Any, ...],
        attempt_directory: Path,
        pool: int,
        selections: tuple[Any, ...] | None = None,
    ) -> Any:
        from immich_memories.analysis.editorial_planner import EditorialSelection
        from immich_memories.analysis.smart_pipeline import PipelineResult
        from immich_memories.api.models import AssetType

        selections = selections or tuple(
            EditorialSelection(
                asset_id=row.clip.asset.id,
                start_time=row.start_time,
                end_time=row.end_time,
                render_mode="motion" if row.clip.asset.type == AssetType.VIDEO else "still",
            )
            for row in candidates
        )
        segments = {row.asset_id: (row.start_time, row.end_time) for row in selections}
        content = round(sum(end - start for start, end in segments.values()), 2)
        stats: dict[str, Any] = {
            "selection_route": "editorial-source",
            "source_evidence": "hermetic launch fixture; no model and no annotation store",
            "legacy_deep_analysis_count": 0,
            "total_analyzed": 0,
            "source_candidate_count": pool,
            "selected_count": len(selections),
            "error_count": 0,
            "editorial_render_adjustments": [],
            "editorial_attempt_directory": str(attempt_directory),
            "elapsed_seconds": self.tracker.progress.elapsed_seconds,
        }
        stats.update(self._timing(selections, candidates, content=content))
        return PipelineResult(
            selected_clips=[row.clip for row in candidates],
            clip_segments=segments,
            errors=[],
            stats=stats,
            editorial_selections=selections,
        )

    def _timing(
        self, selections: tuple[Any, ...], candidates: tuple[Any, ...], *, content: float
    ) -> dict[str, Any]:
        """Certify the render budget exactly as the structure planner does."""
        from immich_memories.processing.editorial_timing import bind_editorial_timeline

        policy = self._context.render_timing
        if policy is None:
            return {
                "editorial_duration_realization": _duration_realization(
                    requested=self._context.target_seconds,
                    budget=content,
                    content=content,
                    slots=len(selections),
                )
            }
        carriers = [
            {"asset_id": row.asset_id, "seconds": row.end_time - row.start_time}
            for row in selections
        ]
        assets = {row.clip.asset.id: row.clip.asset for row in candidates}
        timeline = policy.resolve(carriers, assets)
        return {
            "editorial_render_timing": bind_editorial_timeline(
                policy, timeline, [row["asset_id"] for row in carriers]
            ),
            "editorial_duration_realization": _duration_realization(
                requested=policy.target_seconds,
                budget=timeline.content_budget,
                content=content,
                slots=len(selections),
            ),
        }


def _stand_in_for_models_fetch() -> None:
    import immich_memories.preflight_run as preflight_run
    from immich_memories.preflight import CheckResult, CheckStatus

    def fetched(name: str) -> Any:
        return lambda _config: CheckResult(
            name=name, status=CheckStatus.OK, message="Stands in for `models fetch`"
        )

    # WHY: the pinned exports are 110 MB from Hugging Face, and a hermetic launch
    # reaches no network. Nothing here reads them -- the scripted route replaces
    # every stage that would -- so only the install check has to see them. The
    # output directory check stays real.
    preflight_run.check_encoder = fetched("Encoder")
    preflight_run.check_detector_export = fetched("Sensitive-content detector")

    import immich_memories.web.model_routes as model_routes

    # WHY: the web's model card hashes the real files, so without this a fetched host
    # still offers "Download models" and every capture of a page shows it. Nothing left
    # to acquire is what `models fetch` leaves behind.
    model_routes.acquisition_plan = lambda _config: []
    model_routes.DETECTOR_SNAPSHOTS = ()


def install_fake_editorial_route(
    stage_seconds: float = DEFAULT_STAGE_SECONDS, *, models_fetched: bool = True
) -> None:
    """Point the production pipeline builder at the scripted route.

    Replaces one seam, ``editorial_runtime.build_smart_pipeline``, which both
    the UI and the CLI import at call time. ``models_fetched`` is the host a
    user leaves after `immich-memories models fetch`; False is a first launch
    that skipped it, which the run's install check must refuse.
    """
    import immich_memories.analysis.editorial_runtime as editorial_runtime
    import immich_memories.analysis.place_geocoder as place_geocoder

    if models_fetched:
        _stand_in_for_models_fetch()

    # WHY: fixture trips already have public place names in EXIF. A hermetic
    # browser or CLI run must not ask Nominatim to name them over the internet.
    place_geocoder.nominatim_fetch = lambda *_args, **_kwargs: lambda *_point: None

    def build_smart_pipeline(
        client: Any,
        thumbnail_cache: Any,
        config: Any = None,
        *,
        app_config: Any,
        editorial_context: Any,
        source_pool: Any,
        dry_run: bool = False,
        editorial_ports: Any = None,
    ) -> _FakeEditorialPipeline:
        return _FakeEditorialPipeline(
            app_config=app_config,
            context=editorial_context,
            stage_seconds=stage_seconds,
            client=client,
            companions=companions_of(source_pool),
        )

    # WHY: the two boundaries a hermetic launch has no way to provide. The real
    # builder opens an annotation store this library has never had prepared and
    # a text model provider that is not running, and it is the one seam both
    # entry points go through, so replacing it leaves every other production
    # module -- attempts, projection, review, timing, assembly -- running for real.
    editorial_runtime.build_smart_pipeline = build_smart_pipeline
