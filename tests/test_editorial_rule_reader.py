"""Standard memory products use rules without constructing an inference transport."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from immich_memories.analysis.editorial_final_hash_review import (
    POLICY as FINAL_HASH_REVIEW_POLICY,
)
from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.analysis.editorial_shareability import NEVER_AUTO, FlagRow
from immich_memories.analysis.editorial_story_reading import StoryEpisode
from immich_memories.analysis.editorial_story_slots import allocate_slots
from immich_memories.config_models_editorial import EditorialConfig


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
    # so on_this_day is asserted on its own contract of one shot per year, below.
    attempt = planner.last_attempt_directory
    plan = json.loads((attempt / "plan.private.json").read_text())
    assert plan["reader"] == "rules-v1"
    assert not plan["story"]["thesis"]
    if product == "on_this_day":
        from collections import Counter

        assert Counter(c.asset.file_created_at.year for c in result.selected_clips) == {
            2022: 1,
            2023: 1,
            2024: 1,
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


def _sparse_asset(asset_id, *, at, sharpness=10.0, brightness=128.0):
    return (
        SimpleNamespace(
            id=asset_id,
            file_created_at=at,
            is_favorite=False,
            is_video=False,
            people=[],
            faces=[],
            exif_info=None,
        ),
        sharpness,
        brightness,
    )


def _sparse_source(assets, pixel_facts, *, target_seconds=0.0, never_auto_ids=()):
    flag = FlagRow(asset_id="", flag=NEVER_AUTO, reason="", source="detector")
    return SimpleNamespace(
        assets=assets,
        annotations={},
        audience_annotations={},
        pixel_facts=pixel_facts,
        shareability_flags=dict.fromkeys(never_auto_ids, (flag,)),
        owner_required_asset_ids=(),
        gps={},
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=None, homebase_longitude=None)
        ),
        case=SimpleNamespace(target_seconds=target_seconds),
        intent=SimpleNamespace(product="monthly_highlights"),
    )


def _sparse_weeks(n, *, target_seconds=0.0, indicated=(), base=datetime(2024, 1, 1, 12)):
    """`n` at-home weeks, one moment and one clean asset each; `indicated` week indexes
    keep a non-"none" weight, as a real occasion indicator would have left them."""
    assets, pixel_facts, moment_asset_ids = {}, {}, {}
    stories, by_key, hints = [], {}, {}
    for week in range(n):
        asset_id = f"a{week}"
        day = base + timedelta(weeks=week)
        asset, sharp, bright = _sparse_asset(asset_id, at=day)
        assets[asset_id] = asset
        pixel_facts[asset_id] = (sharp, bright)
        moment = f"m{week}"
        moment_asset_ids[moment] = (asset_id,)
        key = f"S{week:03}"
        by_key[key] = StoryEpisode(key, f"week {week}", "", "", "supporting", "", moments=[moment])
        stories.append(
            {"key": key, "episodes": [key], "weight": "minor" if week in indicated else "none"}
        )
        hints[key] = {"day": day.date().isoformat()}
    source = _sparse_source(assets, pixel_facts, target_seconds=target_seconds)
    source.moment_asset_ids = moment_asset_ids
    return source, stories, by_key, hints


def test_a_mostly_indicated_household_leaves_bare_weeks_short():
    """Control: 7 of 10 weeks carry an indicator. The three bare weeks stay 'none' with
    no grant, exactly the 2026-09-23 rule."""
    source, stories, by_key, hints = _sparse_weeks(10, target_seconds=300.0, indicated=range(7))
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert audit["promoted"] == []
    assert audit["left_short"] == []
    assert {s["key"] for s in stories if s["weight"] == "none"} == {"S007", "S008", "S009"}


def test_a_mostly_bare_household_funds_its_weeks_from_their_best_picture():
    """The pets shape, simplified: 13 of 14 weeks are bare; each is promoted to glimpse,
    funded by its own week's picture."""
    source, stories, by_key, hints = _sparse_weeks(14, target_seconds=300.0, indicated=(13,))
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert len(audit["promoted"]) == 13
    assert audit["left_short"] == []
    bare = [s for s in stories if s["key"] != "S013"]
    assert all(s["weight"] == "glimpse" for s in bare)
    assert all(s["funded_by"] == "quality" for s in bare)
    assert all(s["quality_asset_id"] == f"a{int(s['key'][1:])}" for s in bare)
    assert next(s for s in stories if s["key"] == "S013")["weight"] == "minor"


def test_a_sharp_frame_is_picked_over_a_soft_one_in_the_same_week():
    source, stories, by_key, hints = _sparse_weeks(1, target_seconds=300.0)
    # A second, blurrier picture joins the lone clean one in the same week's moment.
    soft_id = "soft0"
    soft_asset, _, _ = _sparse_asset(soft_id, at=datetime(2024, 1, 1, 13))
    source.assets[soft_id] = soft_asset
    source.pixel_facts[soft_id] = (0.1, 128.0)
    source.annotations[soft_id] = "resolution:4032x3024 SOFT (blurry)"
    source.moment_asset_ids["m0"] = ("a0", soft_id)

    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert audit["promoted"] == ["S000"]
    assert stories[0]["quality_asset_id"] == "a0"


def test_a_junk_only_week_stays_unfunded_with_its_reason():
    source, stories, by_key, hints = _sparse_weeks(1, target_seconds=300.0)
    # The week's only picture is a screenshot: no clean candidate exists.
    source.audience_annotations["a0"] = SimpleNamespace(heads=(("screen", "yes"),))

    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert audit["promoted"] == []
    assert audit["left_short"] == ["S000"]
    assert stories[0]["weight"] == "none"
    assert stories[0]["sparse_quality_reason"] == "No clean picture of the week"


def test_a_light_user_gets_at_most_one_week_per_free_slot():
    """40 bare weeks, a 300 s target (75 slots): every week fits, so every week is funded."""
    source, stories, by_key, hints = _sparse_weeks(40, target_seconds=300.0)
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert len(audit["promoted"]) == min(40, len(stories))


def test_a_light_user_s_promotions_spread_across_the_period_when_capped():
    """A target too small for every bare week caps the grant at its slot count, spread
    across the period rather than taken from one end of it."""
    source, stories, by_key, hints = _sparse_weeks(40, target_seconds=80.0)  # 20 slots
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert len(audit["promoted"]) == 20
    assert "S000" in audit["promoted"]
    assert "S039" in audit["promoted"]


def test_the_exact_two_thirds_boundary_promotes():
    source, stories, by_key, hints = _sparse_weeks(3, target_seconds=300.0, indicated=(2,))
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert audit["share"] == pytest.approx(2 / 3, abs=1e-3)
    assert set(audit["promoted"]) == {"S000", "S001"}


def test_just_under_the_boundary_leaves_bare_weeks_short():
    source, stories, by_key, hints = _sparse_weeks(3, target_seconds=300.0, indicated=(1, 2))
    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)

    assert audit["share"] == pytest.approx(1 / 3, abs=1e-3)
    assert audit["promoted"] == []


def test_the_pets_shape_funds_bare_weeks_so_the_walk_no_longer_takes_the_leftovers():
    """14 weekly cat photos, one week with a video and a town walk: the 13 bare weeks are
    promoted and each claims its own glimpse slot before the walk's leftovers do, unlike
    before #2048 where the walk's many moments took every slot the film had."""
    source, stories, by_key, hints = _sparse_weeks(14, target_seconds=300.0, indicated=(13,))
    for story in stories:
        story["first_day"] = hints[story["key"]]["day"]
    walk = next(s for s in stories if s["key"] == "S013")
    walk["weight"] = "major"

    audit = RuleStructureReader(source)._promote_sparse_quality(stories, by_key, hints)
    assert len(audit["promoted"]) == 13

    capacity = {s["key"]: (37 if s["key"] == "S013" else 1) for s in stories}
    granted = allocate_slots(stories, 20, capacity)

    assert all(granted[key] == 1 for key in granted if key != "S013")
    assert granted["S013"] == 7  # 20 slots - the 13 glimpses the bare weeks claimed first
