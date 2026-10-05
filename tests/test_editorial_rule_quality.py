"""The picture that carries a moment is chosen on capture facts, not on capture order."""

from datetime import UTC, datetime
from types import SimpleNamespace

from immich_memories.analysis.editorial_rule_episodes import RuleEpisodeReader
from immich_memories.analysis.editorial_rule_quality import (
    picture_facts,
    promote_quality_choice,
    quality_facts,
    quality_key,
    representative_key,
    rule_representative_rank,
)
from immich_memories.analysis.editorial_story_shortlist import (
    DepictedChoice,
    _capture_group_moments,
)


def _asset(asset_id, *, minute=0, favourite=False, video=False, people=(), faces=()):
    return SimpleNamespace(
        id=asset_id,
        is_favorite=favourite,
        is_video=video,
        people=list(people),
        faces=list(faces),
        file_created_at=datetime(2024, 6, 1, 10, minute, tzinfo=UTC),
        exif_info=None,
    )


def _order(entries):
    """entries: (asset, line, residual), in capture order. Returns the ids best first."""
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: representative_key(
            picture_facts(
                pair[1][0],
                line=pair[1][1],
                place=pair[0],
                of=len(entries),
                residual=pair[1][2],
            )
        ),
    )
    return [entry[0].id for _place, entry in ranked]


def test_the_owner_s_favourite_leads_whatever_else_is_in_the_group():
    plain = (_asset("plain", minute=0, video=True, people=["a", "b"]), "", None)
    star = (_asset("star", minute=1, favourite=True), "SOFT (blurry)", None)

    assert _order([plain, star])[0] == "star"


def test_a_video_leads_the_stills_of_its_moment():
    still = (_asset("still", minute=0, people=["a"]), "", None)
    clip = (_asset("clip", minute=1, video=True), "", None)

    assert _order([still, clip])[0] == "clip"


def test_a_live_photo_with_measured_motion_counts_as_motion():
    still = (_asset("still", minute=0), "", None)
    moving = (_asset("moving", minute=1), "", 2.4)

    assert _order([still, moving])[0] == "moving"


def test_a_still_motion_was_measured_on_and_found_lacking_does_not():
    still = (_asset("still", minute=0), "", None)
    barely = (_asset("barely", minute=1), "", 0.4)

    assert _order([still, barely])[0] == "still"


def test_more_named_people_lead_fewer():
    one = (_asset("one", minute=0, people=["a"]), "", None)
    three = (_asset("three", minute=1, people=["a", "b", "c"]), "", None)

    assert _order([one, three])[0] == "three"


def test_the_frame_that_shows_the_named_subject_leads_the_one_he_is_a_speck_in():
    """The shipped subject-framing rung survives in the no-model order."""
    speck = (_asset("speck", minute=0, people=["a"]), "subject-framing:1 (0.20% of the frame", None)
    shown = (_asset("shown", minute=1, people=["a"]), "subject-framing:3 (6.00% of the frame", None)

    assert _order([speck, shown])[0] == "shown"


def test_a_pixel_warning_falls_behind_a_clean_frame():
    soft = (_asset("soft", minute=0), "resolution:4032x3024 SOFT (blurry)", None)
    clean = (_asset("clean", minute=1), "resolution:4032x3024", None)

    assert _order([soft, clean])[0] == "clean"


def test_an_obstructed_frame_loses_to_its_clean_sibling():
    """#2022: a flagged picture loses to a clean sibling; this never drops either shot."""
    flagged = (_asset("flagged", minute=0), "resolution:4032x3024 OBSTRUCTED (edge)", None)
    clean = (_asset("clean", minute=1), "resolution:4032x3024", None)

    assert _order([flagged, clean])[0] == "clean"


def test_the_favourite_still_wins_even_when_obstructed():
    """#2022: a favourite is never overruled by a rank-only warning."""
    favourite = (
        _asset("favourite", minute=0, favourite=True),
        "resolution:4032x3024 OBSTRUCTED (edge)",
        None,
    )
    clean = (_asset("clean", minute=1), "resolution:4032x3024", None)

    assert _order([favourite, clean])[0] == "favourite"


def test_a_head_that_saw_somebody_leads_one_that_saw_nobody():
    empty = (_asset("empty", minute=0), "people=none", None)
    somebody = (_asset("somebody", minute=1), "people=two", None)

    assert _order([empty, somebody])[0] == "somebody"


def test_the_middle_of_a_burst_leads_its_first_frame():
    burst = [(_asset(f"f{n}", minute=n), "", None) for n in range(5)]

    assert _order(burst)[0] == "f2"


def test_two_pictures_that_tie_everywhere_keep_the_earlier_one_first():
    pair = [(_asset("early", minute=0), "", None), (_asset("late", minute=1), "", None)]

    assert _order(pair) == ["early", "late"]


def _units(ids):
    return [
        {"asset_id": a, "moment": "M01", "taken": f"2024-06-01T10:0{n}:00", "favourite": False}
        for n, a in enumerate(ids)
    ]


def test_the_capture_group_hands_its_moment_to_the_best_ranked_picture():
    assets = {
        "first": _asset("first", minute=0),
        "best": _asset("best", minute=1, people=["a", "b"]),
        "last": _asset("last", minute=2),
    }

    choices = _capture_group_moments(
        _units(["first", "best", "last"]),
        quality=lambda _a: 1.0,
        rank=rule_representative_rank(assets, {}, {}),
    )

    assert choices[0].primary == "best"


def test_without_the_rules_rank_the_capture_group_keeps_the_sharpest_picture():
    choices = _capture_group_moments(
        _units(["first", "best", "last"]),
        quality=lambda a: 5.0 if a == "last" else 1.0,
    )

    assert choices[0].primary == "last"


class _Annotations:
    contract = SimpleNamespace(renderer_version="r", producer_versions=("p",))

    def __init__(self, lines):
        self._lines = lines

    def lines_for(self, asset_ids):
        return SimpleNamespace(
            as_mapping=lambda: {a: self._lines.get(a, "") for a in asset_ids},
            contract=self.contract,
        )


def _projection(assets):
    candidates = [
        SimpleNamespace(
            asset_id=a.id, favourite=a.is_favorite, source=a, taken_at=a.file_created_at
        )
        for a in assets
    ]
    group = SimpleNamespace(
        group_id="G01",
        candidate_ids=tuple(c.asset_id for c in candidates),
        candidates=candidates,
    )
    return SimpleNamespace(group=group)


def _card(assets, *, by_quality):
    lines = {a.id: f"resolution:4032x3024 for {a.id}" for a in assets}
    reader = RuleEpisodeReader(_Annotations(lines), by_quality=by_quality)
    result = reader.read([_projection(assets)])
    return result.episodes[0].reading.representatives[0]


def test_the_episode_card_names_the_best_ranked_picture_for_a_rules_reader():
    assets = [_asset("first", minute=0), _asset("best", minute=1, people=["a"])]

    assert _card(assets, by_quality=True).asset_id == "best"


def test_the_episode_card_keeps_the_first_capture_when_it_stands_in_for_a_model():
    assets = [_asset("first", minute=0), _asset("best", minute=1, people=["a"])]

    assert _card(assets, by_quality=False).asset_id == "first"


# -- a sparse week's best picture (#2048) -------------------------------------------------


def _quality(
    asset,
    *,
    line="",
    heads=None,
    standing=1,
    sharpness=10.0,
    floor=5.0,
    brightness=128.0,
    distance=0.0,
    never_auto=False,
):
    return quality_facts(
        asset,
        line=line,
        heads=heads or {},
        standing=standing,
        sharpness=sharpness,
        sharpness_floor=floor,
        brightness=brightness,
        distance_from_midweek=distance,
        never_auto=never_auto,
    )


def test_a_soft_warning_disqualifies_a_candidate():
    assert _quality(_asset("soft"), line="resolution:4032x3024 SOFT (blurry)").disqualified


def test_a_rotated_warning_disqualifies_a_candidate():
    assert _quality(_asset("rotated"), line="resolution:4032x3024 rotated").disqualified


def test_an_obstructed_warning_does_not_disqualify_a_candidate():
    """#2022: rank-only. A sparse week's lone flagged carrier is still its pick."""
    assert not _quality(_asset("edge"), line="resolution:4032x3024 OBSTRUCTED (edge)").disqualified


def test_standing_below_one_disqualifies_a_candidate():
    assert _quality(_asset("low"), standing=0).disqualified


def test_sharpness_below_the_library_floor_disqualifies_a_candidate():
    assert _quality(_asset("blurry"), sharpness=1.0, floor=5.0).disqualified


def test_a_screenshot_head_disqualifies_a_candidate():
    assert _quality(_asset("screenshot"), heads={"screen": "yes"}).disqualified


def test_a_document_head_disqualifies_a_candidate():
    assert _quality(_asset("doc"), heads={"doc_docling": "document"}).disqualified


def test_a_never_auto_flag_disqualifies_a_candidate():
    assert _quality(_asset("held"), never_auto=True).disqualified


def test_a_clean_candidate_is_not_disqualified():
    assert not _quality(_asset("clean")).disqualified


def test_quality_key_prefers_faces_present():
    nobody = _quality(_asset("nobody"), line="people=none")
    somebody = _quality(_asset("somebody", people=["a"]), line="people=one")

    ordered = sorted([nobody, somebody], key=quality_key)
    assert ordered[0] is somebody


def test_quality_key_prefers_the_sharper_frame_up_to_the_cap():
    sharp = _quality(_asset("sharp"), sharpness=50.0, floor=5.0)
    soft = _quality(_asset("soft2"), sharpness=6.0, floor=5.0)

    assert quality_key(sharp) < quality_key(soft)


def test_quality_key_caps_the_sharpness_lead_at_four_times_the_floor():
    way_sharper = _quality(_asset("huge"), sharpness=500.0, floor=5.0)
    four_times = _quality(_asset("four"), sharpness=20.0, floor=5.0)

    assert way_sharper.sharpness_ratio == four_times.sharpness_ratio == 4.0


def test_quality_key_prefers_exposure_closest_to_mid_grey():
    mid = _quality(_asset("mid"), brightness=128.0)
    dim = _quality(_asset("dim"), brightness=60.0)

    assert quality_key(mid) < quality_key(dim)


def test_quality_key_prefers_nearness_to_midweek():
    near = _quality(_asset("near"), distance=10.0)
    far = _quality(_asset("far"), distance=10000.0)

    assert quality_key(near) < quality_key(far)


def _promote(eligible, asset_id, *, stands=lambda _a: True, free=lambda _a: True):
    return promote_quality_choice(eligible, asset_id, stands=stands, free=free)


def test_promote_quality_choice_surfaces_the_chosen_moment_first():
    other = DepictedChoice(
        key="c1", episode="e1", taken="2024-06-01T10:00:00", content="", primary="x"
    )
    holder = DepictedChoice(
        key="c2",
        episode="e2",
        taken="2024-06-01T10:01:00",
        content="",
        primary="y",
        alternatives=["z"],
    )

    ordered = _promote([other, holder], "z")

    assert ordered[0].key == "c2"
    assert ordered[0].primary == "z"
    assert ordered[1] is other


def test_promote_quality_choice_goes_short_without_an_asset_id():
    choice = DepictedChoice(key="c1", episode="e1", taken="t", content="", primary="x")

    assert _promote([choice], None) == []


def test_promote_quality_choice_goes_short_when_the_chosen_asset_does_not_stand():
    """A week's quality pick ran before the carrier gate ever saw this asset; if the gate
    now refuses it, the week goes short rather than forcing a gate-failed primary (#2048
    review, point B)."""
    choice = DepictedChoice(key="c1", episode="e1", taken="t", content="", primary="x")

    assert _promote([choice], "x", stands=lambda _a: False) == []


def test_promote_quality_choice_goes_short_when_the_chosen_asset_is_not_free():
    choice = DepictedChoice(key="c1", episode="e1", taken="t", content="", primary="x")

    assert _promote([choice], "x", free=lambda _a: False) == []


def test_promote_quality_choice_goes_short_when_the_chosen_asset_is_not_in_any_eligible_choice():
    choice = DepictedChoice(key="c1", episode="e1", taken="t", content="", primary="x")

    assert _promote([choice], "not-offered") == []
