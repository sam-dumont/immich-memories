"""Canonical events remain exact from discovery through production and wall source.

The probe and matrix script inspections stay on the probe branch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.analysis.editorial_rule_reader import NoModelJudge
from immich_memories.analysis.editorial_runtime import (
    EditorialRunContext,
    build_editorial_planner,
)
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_source import fetch_full_window_source
from immich_memories.analysis.editorial_structure_contract import (
    StructurePlannerPorts,
    StructurePlanningResult,
)
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.selection_trace import Trace
from immich_memories.analysis.smart_pipeline import ClipWithSegment
from immich_memories.analysis.special_event_scope import (
    SpecialEventAdmission,
    validate_special_event_scope,
)
from immich_memories.automation.catalogue import entries_from
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange
from tests.conftest import make_asset, make_clip
from tests.test_editorial_runtime import _seed_descriptions

WINDOW = DateRange(datetime(2020, 6, 14, tzinfo=UTC), datetime(2020, 6, 14, 23, 59, tzinfo=UTC))


def event_id(members):
    digest = hashlib.sha256(json.dumps(sorted(members), separators=(",", ":")).encode()).hexdigest()
    return f"special-event-{digest[:24]}"


def record(members, key="event"):
    return {
        "key": key,
        "label": "An occasion",
        "product": "special_day",
        "brief": "A memory.",
        "target_seconds": 60,
        "ranges": [
            {"start": WINDOW.start.date().isoformat(), "end": WINDOW.end.date().isoformat()}
        ],
        "event_id": event_id(members),
        "asset_ids": list(members),
        "what": "An occasion",
        "start": WINDOW.start.isoformat(),
        "end": WINDOW.end.isoformat(),
    }


def load_script(name):
    path = Path(__file__).parents[1] / "scripts" / name
    if str(path.parents[0]) not in sys.path:
        sys.path.insert(0, str(path.parents[0]))
    spec = importlib.util.spec_from_file_location(name.replace("/", "_"), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "identity,members",
    [
        (None, ("asset",)),
        (event_id(("asset",)), ()),
        (event_id(("asset",)), ("other",)),
        (event_id(("asset",)), ("asset", "asset")),
    ],
)
def test_incomplete_or_changed_membership_cannot_become_a_day(identity, members):
    with pytest.raises(ValueError):
        validate_special_event_scope(identity, members)


def test_catalogue_rejects_missing_exact_window_instead_of_using_day():
    with pytest.raises(ValueError, match="exact start and end"):
        entries_from([{"day": "2020-06-14", "event_id": event_id(("a",)), "asset_ids": ["a"]}])


def test_exact_source_filters_overreturn_before_annotation_and_keeps_live_link():
    still = make_asset("race", file_created_at=WINDOW.start)
    still.live_photo_video_id = "race-motion"
    other = make_asset("festival", file_created_at=WINDOW.start)
    standalone = make_asset("race-video", file_created_at=WINDOW.start)
    companion = make_asset("race-motion", file_created_at=WINDOW.start)

    class Client:
        def get_videos_for_date_range(self, dates):
            return [companion, standalone]

        def get_photos_for_date_range(self, dates, person_id=None, person_ids=None):
            return [other, still]

    members = ("race", "race-video")
    sources = fetch_full_window_source(
        Client(), SourceScope(date_ranges=(WINDOW,), asset_ids=members)
    )
    # The member still's companion travels with it (how it plays); the day's others do not.
    assert {s.id for s in sources} == {*members, "race-motion"}
    assert next(s for s in sources if s.id == "race").live_photo_video_id == "race-motion"
    seen_by_evidence = []
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(SourceScope(date_ranges=(WINDOW,), asset_ids=members)),
        EditorialDependencies(
            source_fetcher=lambda _scope: (other, still, companion, standalone),
            source_evidence=lambda source: seen_by_evidence.append(source.id),
        ),
    )
    assert set(prepared.candidate_ids) == set(members)
    assert set(seen_by_evidence) == set(members)
    assert set(prepared.excluded_ids) == {"festival", "race-motion"}
    assert (
        fetch_full_window_source(
            Client(), SourceScope(date_ranges=(WINDOW,), asset_ids=("missing",))
        )
        == ()
    )
    assert len(fetch_full_window_source(Client(), SourceScope(date_ranges=(WINDOW,)))) == 4


@pytest.mark.parametrize("member", ["race", "festival"])
@pytest.mark.parametrize("admitted", [False, True])
def test_production_wall_receives_only_selected_event_even_if_port_returns_whole_day(
    tmp_path, member, admitted
):
    clips = {
        name: make_clip(name, file_created_at=WINDOW.start.replace(hour=10))
        for name in ("race", "festival")
    }
    _seed_descriptions({member: "People share an occasion."})
    config = Config(
        llm={"model": "fake-model"},
        editorial={
            "enabled": True,
            "description_model": "student-v1",
        },
    )
    context = EditorialRunContext(
        key="same-date",
        label="An occasion",
        product="special_day",
        date_ranges=(WINDOW,),
        target_seconds=60,
        artifact_dir=tmp_path / "artifacts",
        special_event_id=event_id((member,)),
        event_asset_ids=(member,),
        event_admission=SpecialEventAdmission.from_catalogue_record(
            record((member,)), evidence_ref="private/catalogue.json"
        )
        if admitted
        else None,
    )
    captured = []

    def plan(source, effects):
        captured.append(source)
        assert tuple(source.assets) == (member,)
        assert set(source.annotations) == {member}
        assert {key for ids in source.moment_asset_ids.values() for key in ids} == {member}
        assert source.case.special_event_id == context.special_event_id
        assert source.case.event_asset_ids == (member,)
        assert source.case.event_admission == context.event_admission
        assert ("already admitted event" in source.intent.narrative_objective) == admitted
        return StructurePlanningResult(
            {
                "carriers": [
                    {
                        "asset_id": member,
                        "taken": WINDOW.start.replace(hour=10).isoformat(),
                        "kind": "video",
                    }
                ]
            },
            "contract",
            "sheet",
            {},
        )

    episode = {
        "schema_version": "episode-reading-text-v1",
        "episodes": [
            {
                "episode": 1,
                "what_happened": "People share an occasion.",
                "representatives": [{"asset": 1, "reason": "The occasion."}],
                "cull": [],
            }
        ],
    }
    planner = build_editorial_planner(
        client=object(),
        config=config,
        thumbnail_cache=object(),
        context=context,
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_full_source=lambda _client, _scope: tuple(clips.values()),
            episode_requester_factory=lambda _config: lambda _prompt: json.dumps(episode),
            structure_planner=plan,
            structure_ports_factory=lambda _source: StructurePlannerPorts(
                judge=NoModelJudge(), thumbnail_hash=lambda _asset: None
            ),
        ),
    )
    result = planner.plan(
        tuple(ClipWithSegment(clip, 0, 5, 1) for clip in clips.values()), trace=Trace()
    )
    assert [row.asset_id for row in result.selections] == [member], result
    assert len(captured) == 1
    other = "festival" if member == "race" else "race"
    with pytest.raises(ValueError, match="exceeds exact special event membership"):
        replace(
            captured[0],
            case=replace(
                captured[0].case,
                special_event_id=event_id((other,)),
                event_asset_ids=(other,),
                event_admission=None,
            ),
        )


def test_an_events_live_photo_with_real_motion_plays_as_its_clip(tmp_path):
    """An event names its pictures, not their Live companions; the companion still comes
    with its still, so a moving Live Photo with its subject in frame plays in the event's
    film and the finished cut breaks no motion promise."""
    from dataclasses import replace as with_facts
    from datetime import timedelta

    from immich_memories.analysis.editorial_cut_invariants import broken_promises
    from immich_memories.analysis.editorial_structure_planner import plan_structure
    from immich_memories.analysis.smart_pipeline import SmartPipeline
    from immich_memories.api.models import AssetType
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from tests.editorial_story_fixtures import ControlledStoryJudge
    from tests.test_editorial_rule_reader import _distinct_preview

    at = WINDOW.start.replace(hour=10)
    stills = [
        make_asset(
            f"still-{n}", duration=None, file_created_at=at + timedelta(minutes=n)
        ).model_copy(update={"type": AssetType.IMAGE, "live_photo_video_id": f"motion-{n}"})
        for n in range(3)
    ]
    companions = [
        make_asset(s.live_photo_video_id, file_created_at=s.file_created_at).model_copy(
            update={"type": AssetType.VIDEO, "duration_seconds": 2.8}
        )
        for s in stills
    ]
    members = tuple(s.id for s in stills)
    config = Config(
        cache={"directory": str(tmp_path / "cache")}, analysis={"min_source_short_side": 0}
    )
    config.editorial.preparation.tier = "metadata_only"
    seen = []

    def plan(source, _ports):
        seen.append(source)
        # The residual a cut already measured and banked: far above the discriminant.
        moving = with_facts(source, motion_residuals={a: {"residual": 4.96} for a in members})
        return plan_structure(
            moving,
            StructurePlannerPorts(judge=ControlledStoryJudge(), thumbnail_hash=lambda _: None),
        )

    planner = build_editorial_planner(
        client=object(),
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "thumbnails"),
        context=EditorialRunContext(
            key="event",
            label="An occasion",
            product="special_day",
            date_ranges=(WINDOW,),
            target_seconds=60,
            artifact_dir=tmp_path / "artifacts",
            special_event_id=event_id(members),
            event_asset_ids=members,
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_full_source=lambda *_: (*stills, *companions),
            fetch_preview=lambda _client, key: _distinct_preview(key),
            structure_planner=plan,
        ),
    )
    SmartPipeline(planner=planner).run_editorial_source(stills, include_live_photos=True)

    ((source,),) = [seen]
    assert set(source.companion_assets) == {c.id for c in companions}
    carriers = json.loads((planner.last_attempt_directory / "plan.private.json").read_text())[
        "carriers"
    ]
    assert carriers
    assert all(c["kind"] == "live-motion" for c in carriers), [c["kind"] for c in carriers]
    assert broken_promises(planner.last_attempt_directory) == 0
