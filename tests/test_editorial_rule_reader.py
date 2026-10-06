"""Standard memory products use rules without constructing an inference transport."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from immich_memories.analysis.editorial_final_hash_review import (
    POLICY as FINAL_HASH_REVIEW_POLICY,
)
from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.analysis.editorial_story_slots import allocate_slots
from immich_memories.config_models_editorial import EditorialConfig, EditorialPeopleConfig


def test_reader_resolution_preserves_explicit_choice_and_uses_rules_without_model():
    assert EditorialConfig().resolve_reader("") == "rules"
    assert EditorialConfig().resolve_reader(" configured-model ") == "model"
    assert EditorialConfig(reader="rules").resolve_reader("configured-model") == "rules"
    with pytest.raises(ValueError, match="nonblank LLM model"):
        EditorialConfig(reader="model").resolve_reader(" ")
    with pytest.raises(ValueError):
        EditorialConfig(reader="anything")


@pytest.mark.parametrize(
    "product",
    [
        "monthly_highlights",
        "person_spotlight",
        "multi_person",
        "special_day",
        "trip",
        "year_in_review",
        "season",
        "holiday",
        "album",
        "on_this_day",
        "custom",
    ],
)
def test_rules_finish_product_selection_without_constructing_inference(tmp_path, product):
    import json
    from datetime import timedelta

    from immich_memories.analysis.editorial_runtime import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
    from immich_memories.analysis.smart_pipeline import SmartPipeline
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.config_loader import Config
    from immich_memories.timeperiod import DateRange
    from tests.test_editorial_runtime import _window
    from tests.test_editorial_source_route import photo

    first = _window(2024, 2, 1)
    window = DateRange(first.start, first.end + timedelta(days=27))
    sources = [photo(f"p-{n:02}", at=window.start + timedelta(days=n, hours=9)) for n in range(22)]
    windows = (window,)
    if product == "on_this_day":
        windows = tuple(_window(year, 2, 1) for year in (2022, 2023, 2024))
        sources = [
            photo(f"p-{part.start.year}-{n}", at=part.start + timedelta(hours=n + 8))
            for part in windows
            for n in range(6)
        ]
        for asset in sources:
            asset.is_favorite = True
    for asset in sources[:3] if product != "album" else ():
        asset.is_favorite = True
    config = Config(
        cache={"directory": str(tmp_path / "cache")},
        analysis={"min_source_short_side": 0},
    )
    # Rules-only component coverage keeps model acquisition outside this fixture.
    config.editorial.preparation.tier = "metadata_only"

    def forbidden(*args, **kwargs):
        pytest.fail("rules reader constructed an inference transport")

    cache = ThumbnailCache(tmp_path / "thumbnails")
    planner = build_editorial_planner(
        client=object(),
        config=config,
        thumbnail_cache=cache,
        context=EditorialRunContext(
            "rules",
            "February",
            product,
            () if product == "album" else windows,
            60,
            tmp_path / "artifacts",
            album_sources=tuple(sources) if product == "album" else (),
            album_ref="fixture-album" if product == "album" else None,
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_full_source=lambda *_: sources,
            fetch_preview=lambda _client, key: _distinct_preview(key),
            episode_requester_factory=forbidden,
        ),
    )
    _, result = SmartPipeline(planner=planner).run_editorial_source(sources)
    assert result.selected_clips
    if product == "album":
        assert len(result.selected_clips) >= 3
    elif product != "on_this_day":
        assert sources[0].id in {clip.asset.id for clip in result.selected_clips}
    # A one-shot grant now takes the middle favourite of its story rather than its first,
    # so on_this_day is asserted on its own contract of a shot in every year, below.
    attempt = planner.last_attempt_directory
    plan = json.loads((attempt / "plan.private.json").read_text())
    assert plan["reader"] == "rules-v1"
    assert not plan["story"]["thesis"]
    if product == "on_this_day":
        assert {c.asset.file_created_at.year for c in result.selected_clips} == {
            2022,
            2023,
            2024,
        }
    else:
        # The twenty-two day fixture is no longer one story but four weekly ones, so the
        # assertion is on the story holding the owner's favourites. Its other three weeks
        # carry no indicator at all: mostly bare, so BASIC funds them from their own best
        # picture instead of going short (#2048), rather than leaving them "none".
        expected = "minor" if product == "album" else "major"
        assert expected in {e["weight"] for e in plan["story"]["episodes"]}
        assert {e["weight"] for e in plan["story"]["episodes"]} <= {expected, "none", "glimpse"}
    assert all(plan["story"]["calls"][key] == 0 for key in ("story_pages", "pick_calls"))
    assert all(row["kind"] != "live-motion" for row in plan["carriers"])
    assert "picture_facts" not in plan
    # The cut ends with a duplicate review of its own rather than reporting it unavailable.
    assert plan["final_duplicate_review"]["status"] in {"complete", "incomplete"}
    assert plan["final_duplicate_review"]["policy"] == FINAL_HASH_REVIEW_POLICY
    # A refused frame is refilled from its own moment or its story before the film shortens,
    # so the record always says where every slot it touched came from.
    assert set(plan["final_duplicate_review"]["replaced_from"]) <= {"moment", "story"}
    assert all(
        row.get("replacement") in {None, *(c["asset_id"] for c in plan["carriers"])}
        for row in plan["final_duplicate_review"]["removals"]
    )
    import sqlite3

    with sqlite3.connect(
        config.editorial.resolve_annotation_database(config.cache.cache_path)
    ) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables.intersection({"editorial_episode_readings", "editorial_period_insights"})


def _distinct_preview(key):
    import hashlib
    import io

    import numpy as np
    from PIL import Image

    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4])
    pixels = np.random.default_rng(seed).integers(30, 220, (128, 128, 3), dtype=np.uint8)
    out = io.BytesIO()
    Image.fromarray(pixels).save(out, format="JPEG")
    return out.getvalue()


def test_rules_refuse_free_text_subjects_before_creating_an_annotation_store(tmp_path):
    from immich_memories.analysis.editorial_runtime import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.config_loader import Config
    from tests.test_editorial_runtime import _window

    database = tmp_path / "annotations.sqlite"
    config = Config(editorial={"reader": "rules", "annotation_database": str(database)})
    with pytest.raises(ValueError, match="written subject needs a model reader"):
        build_editorial_planner(
            client=object(),
            config=config,
            thumbnail_cache=ThumbnailCache(tmp_path / "previews"),
            context=EditorialRunContext(
                "custom",
                "Pictures about perseverance",
                "custom",
                (_window(2024, 2, 1),),
                60,
                tmp_path / "artifacts",
                base_brief="Pictures about perseverance",
            ),
        )
    assert not database.exists()


def test_only_happening_in_required_partition_is_maybe_without_an_occasion_flag():
    from types import SimpleNamespace

    from immich_memories.analysis.editorial_intent import build_editorial_intent
    from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
    from tests.test_editorial_runtime import _window
    from tests.test_editorial_source_route import photo

    window = _window(2024, 2, 1)
    asset = photo("only", at=window.start)
    source = SimpleNamespace(
        assets={asset.id: asset},
        annotations={},
        intent=build_editorial_intent("monthly_highlights", (window,), brief="February"),
    )
    wall = SimpleNamespace(fam_ids=["f"], event_assets={"f": [asset.id]})
    tiers, reasons = RuleStructureReader(source).worthiness(wall, lambda _: None)
    assert tiers == {"f": 1}
    assert "required" in reasons["f"]


@pytest.mark.parametrize(
    ("last_day_mass", "near_home", "expected"), [(3, True, 2), (4, True, 0), (3, False, 0)]
)
def test_occasion_threshold_and_away_flag(last_day_mass, near_home, expected):
    from datetime import timedelta
    from types import SimpleNamespace

    from immich_memories.analysis.editorial_intent import build_editorial_intent
    from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
    from immich_memories.timeperiod import DateRange
    from tests.test_editorial_runtime import _window
    from tests.test_editorial_source_route import photo

    first = _window(2024, 2, 1)
    window = DateRange(first.start, first.end + timedelta(days=9))
    members = {
        str(day): [
            photo(f"{day}-{n}", at=first.start + timedelta(days=day, minutes=n))
            for n in range(last_day_mass if day == 9 else 1)
        ]
        for day in range(10)
    }
    source = SimpleNamespace(
        assets={a.id: a for group in members.values() for a in group},
        annotations={},
        intent=build_editorial_intent("monthly_highlights", (window,), brief="February"),
    )
    wall = SimpleNamespace(
        fam_ids=list(members), event_assets={k: [a.id for a in v] for k, v in members.items()}
    )
    tiers, _ = RuleStructureReader(source).worthiness(wall, lambda _: near_home)
    assert tiers["9"] == expected


def test_a_rules_film_may_play_a_live_photo_and_can_measure_one(tmp_path):
    """Motion is first class on every tier: the rules reader plans with the run's Live Photo
    policy and the same measuring port a model film has, so a clip with real motion and its
    subject in frame plays, and a dull one stays its still."""
    from datetime import timedelta

    from immich_memories.analysis.editorial_runtime import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
    from immich_memories.analysis.editorial_structure_planner import plan_structure
    from immich_memories.analysis.smart_pipeline import SmartPipeline
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.config_loader import Config
    from immich_memories.timeperiod import DateRange
    from tests.test_editorial_runtime import _window
    from tests.test_editorial_source_route import photo

    first = _window(2024, 2, 1)
    window = DateRange(first.start, first.end + timedelta(days=27))
    sources = [photo(f"p-{n:02}", at=window.start + timedelta(days=n, hours=9)) for n in range(8)]
    for asset in sources[:3]:
        asset.is_favorite = True
    config = Config(
        cache={"directory": str(tmp_path / "cache")},
        analysis={"min_source_short_side": 0},
    )
    config.editorial.preparation.tier = "metadata_only"
    seen = []

    def planner_seeing(source, ports):
        seen.append((source, ports))
        return plan_structure(source, ports)

    planner = build_editorial_planner(
        client=object(),
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "thumbnails"),
        context=EditorialRunContext(
            "rules", "February", "monthly_highlights", (window,), 60, tmp_path / "artifacts"
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_full_source=lambda *_: sources,
            fetch_preview=lambda _client, key: _distinct_preview(key),
            structure_planner=planner_seeing,
        ),
    )
    SmartPipeline(planner=planner).run_editorial_source(sources, include_live_photos=True)

    ((source, ports),) = seen
    assert source.allow_live_motion
    assert source.lineage["render_policy"] == {"allow_live_motion": True}
    assert ports.resolve_motion is not None
    assert ports.clock_offsets is not None


# -- sparse weeks funded by quality (#2048) -----------------------------------------------
#
# Driven through the public seam (`RuleStructureReader.read_story`), not the private
# `_promote_sparse_quality` (#2048 review, point F): every week here is its own day,
# a week apart from its neighbours, so `_runs` never merges two weeks into one story.


def _week_source(
    n,
    *,
    indicated=(),
    junk_week=None,
    base=date(2024, 1, 1),
    target_seconds=300.0,
    promote_sparse_quality=True,
):
    """`n` at-home weeks, one moment and one clean asset each. `indicated` week indexes
    read as a real occasion (gate "remarkable"); every other week reads as a quiet one
    (gate "background", which floors to weight "none"). `junk_week` is a screenshot:
    no clean candidate exists for it."""
    assets, moments, annotations, pixel_facts, audience = {}, {}, {}, {}, {}
    for week in range(n):
        asset_id = f"a{week:03}"
        taken = datetime.combine(base + timedelta(weeks=week), datetime.min.time()) + timedelta(
            hours=9
        )
        assets[asset_id] = SimpleNamespace(
            id=asset_id,
            file_created_at=taken,
            is_favorite=False,
            is_video=False,
            exif_info=None,
            people=[],
            faces=[],
        )
        moments[f"W{week:03}"] = (asset_id,)
        annotations[asset_id] = f"{taken.isoformat()} | at home"
        if week == junk_week:
            audience[asset_id] = SimpleNamespace(heads=(("screen", "yes"),))
        else:
            pixel_facts[asset_id] = (10.0, 128.0)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps={},
        annotations=annotations,
        audience_annotations=audience,
        pixel_facts=pixel_facts,
        shareability_flags={},
        owner_required_asset_ids=(),
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=None, homebase_longitude=None),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(product="monthly_highlights"),
        case=SimpleNamespace(
            product="monthly_highlights", people=(), target_seconds=target_seconds
        ),
        people=None,
    )
    reader = RuleStructureReader(source, promote_sparse_quality=promote_sparse_quality)

    def enrich(episodes):
        hints = {}
        for episode in episodes:
            week = int(episode.moments[0][1:])
            day = base + timedelta(weeks=week)
            gate = "remarkable" if week in indicated else "background"
            hints[episode.key] = {
                "day": day.isoformat(),
                "moments": 1,
                "pictures": 1,
                "favourites": 0,
                "gate": gate,
                "relations": {},
            }
        return hints

    return reader, enrich


def _read(reader, enrich):
    return reader.read_story(None, evidence=[], enrich=enrich, record=lambda _r: None)


def _week_of(story_row, story) -> int:
    episode = next(e for e in story.episodes if e.key == story_row["episodes"][0])
    return int(episode.moments[0][1:])


def test_a_mostly_indicated_household_leaves_bare_weeks_short():
    """Control: 7 of 10 weeks carry an indicator. The three bare weeks stay 'none' with
    no grant, and the plan carries no sparse-quality audit at all (#2048 review, point D):
    exactly the 2026-09-23 rule, byte-identical to a plan built before #2048 existed."""
    story = _read(*_week_source(10, indicated=range(7)))

    assert story.audit.get("sparse_quality") is None
    bare = {_week_of(s, story) for s in story.stories if s["weight"] == "none"}
    assert bare == {7, 8, 9}


def test_a_mostly_bare_household_funds_its_weeks_from_their_best_picture():
    """The pets shape, simplified: 13 of 14 weeks are bare; each is promoted to glimpse,
    funded by its own week's picture."""
    story = _read(*_week_source(14, indicated=(13,)))

    bare = [s for s in story.stories if _week_of(s, story) != 13]
    assert len(bare) == 13
    assert all(s["weight"] == "glimpse" for s in bare)
    assert all(s["funded_by"] == "quality" for s in bare)
    assert all(s["quality_asset_id"] == f"a{_week_of(s, story):03}" for s in bare)
    indicated_row = next(s for s in story.stories if _week_of(s, story) == 13)
    assert indicated_row["weight"] == "minor"
    audit = story.audit["sparse_quality"]
    assert len(audit["promoted"]) == 13
    assert audit["left_short"] == []


def test_a_sharp_frame_is_picked_over_a_soft_one_in_the_same_week():
    reader, enrich = _week_source(1)
    # A second, blurrier picture joins the lone clean one in the same week's moment.
    soft_id = "soft0"
    soft_taken = datetime(2024, 1, 1, 13)
    reader.source.assets[soft_id] = SimpleNamespace(
        id=soft_id,
        file_created_at=soft_taken,
        is_favorite=False,
        is_video=False,
        exif_info=None,
        people=[],
        faces=[],
    )
    reader.source.annotations[soft_id] = "resolution:4032x3024 SOFT (blurry)"
    reader.source.moment_asset_ids["W000"] = ("a000", soft_id)

    story = _read(reader, enrich)

    assert story.stories[0]["funded_by"] == "quality"
    assert story.stories[0]["quality_asset_id"] == "a000"


def test_a_junk_only_week_stays_unfunded_with_its_reason():
    """The week's only picture is a screenshot: no clean candidate exists, so it stays
    short, with the reason recorded, even though the household is otherwise sparse enough
    to engage the mechanism."""
    story = _read(*_week_source(3, junk_week=0))

    junk = next(s for s in story.stories if _week_of(s, story) == 0)
    assert junk["weight"] == "none"
    assert junk["sparse_quality_reason"] == "No clean picture of the week"
    assert story.audit["sparse_quality"]["left_short"] == [junk["key"]]


def test_a_light_user_gets_at_most_one_week_per_free_slot():
    """40 bare weeks, a 300 s target (75 slots): every week fits, so every week is funded."""
    story = _read(*_week_source(40, target_seconds=300.0))

    assert len(story.audit["sparse_quality"]["promoted"]) == 40


def test_a_light_user_s_promotions_spread_across_the_period_when_capped():
    """A target too small for every bare week caps the grant at its slot count, spread
    across the period rather than taken from one end of it."""
    story = _read(*_week_source(40, target_seconds=80.0))  # 20 slots

    promoted = story.audit["sparse_quality"]["promoted"]
    assert len(promoted) == 20
    weeks = {_week_of(s, story) for s in story.stories if s["key"] in promoted}
    assert 0 in weeks
    assert 39 in weeks


def test_the_exact_two_thirds_boundary_promotes():
    story = _read(*_week_source(3, indicated=(2,)))

    audit = story.audit["sparse_quality"]
    assert audit["share"] == pytest.approx(2 / 3, abs=1e-3)
    promoted_weeks = {_week_of(s, story) for s in story.stories if s["key"] in audit["promoted"]}
    assert promoted_weeks == {0, 1}


def test_just_under_the_boundary_leaves_bare_weeks_short():
    story = _read(*_week_source(3, indicated=(1, 2)))

    assert story.audit.get("sparse_quality") is None


def test_a_chosen_week_that_fails_its_filters_hands_its_slot_to_the_next_waiting_week():
    """5 bare weeks, 3 free slots: the spread chooses weeks 0, 2 and 4 and leaves 1 and 3
    waiting. Week 0 is a screenshot with no clean picture, so its slot goes to week 1 (the
    next in chronological order) instead of being given up; week 3, never pulled in, is the
    only one left short besides the junk week itself (#2048 review, point E)."""
    story = _read(*_week_source(5, target_seconds=12.0, junk_week=0))

    audit = story.audit["sparse_quality"]
    promoted_weeks = {_week_of(s, story) for s in story.stories if s["key"] in audit["promoted"]}
    left_short_weeks = {
        _week_of(s, story) for s in story.stories if s["key"] in audit["left_short"]
    }
    assert promoted_weeks == {1, 2, 4}
    assert left_short_weeks == {0, 3}


def test_the_full_thin_model_path_never_promotes_a_bare_week():
    """The owner's ruling is BASIC-only (#2048 review, point C): the same mostly-bare shape
    that promotes 13 of 14 weeks under the rules-only reader stays untouched when the
    reader backs a thin model layer's draft."""
    story = _read(*_week_source(14, indicated=(13,), promote_sparse_quality=False))

    assert story.audit.get("sparse_quality") is None
    assert all(s["weight"] in ("none", "minor") for s in story.stories)
    assert all(not s.get("funded_by") for s in story.stories)


def test_the_pets_shape_funds_bare_weeks_so_the_walk_no_longer_takes_the_leftovers():
    """14 weekly cat photos, one week with a video and a town walk: the 13 bare weeks are
    promoted and each claims its own glimpse slot before the walk's leftovers do, unlike
    before #2048 where the walk's many moments took every slot the film had."""
    base = date(2024, 1, 1)
    story = _read(*_week_source(14, indicated=(13,), base=base))
    stories = story.stories
    for s in stories:
        s["first_day"] = (base + timedelta(weeks=_week_of(s, story))).isoformat()
    walk = next(s for s in stories if _week_of(s, story) == 13)
    walk["weight"] = "major"

    assert len(story.audit["sparse_quality"]["promoted"]) == 13

    capacity = {s["key"]: (37 if s is walk else 1) for s in stories}
    granted = allocate_slots(stories, 20, capacity)

    assert all(granted[key] == 1 for key in granted if key != walk["key"])
    assert granted[walk["key"]] == 7  # 20 slots - the 13 glimpses the bare weeks claimed first
