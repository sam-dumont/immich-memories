"""What the pool, the storyboard and the CLI say about a picture's hold, and what they write."""

from __future__ import annotations

from immich_memories.analysis.editorial_structure_audience import AudienceBank
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations import picture_holds as holds
from tests.annotation_rows import add_rows


def config_at(tmp_path):
    del tmp_path  # kept for call-site symmetry; the store is the one this test's env names
    return Config()


def bank_a_head(config, asset_id, label="yes"):
    store = holds.store_of(config)
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": asset_id,
            "head": "nsfw_marqo",
            "version": config.editorial.head_versions["nsfw_marqo"],
            "label": label,
        },
    )


def test_a_picture_nothing_holds_offers_no_clearance(tmp_path):
    config = config_at(tmp_path)

    (hold,) = holds.read(config, ["calm"]).values()

    assert not hold.can_clear
    assert hold.describe() == ""


def test_a_detector_hold_is_named_and_can_be_cleared(tmp_path):
    config = config_at(tmp_path)
    bank_a_head(config, "beach")

    hold = holds.read(config, ["beach"])["beach"]

    assert hold.can_clear and hold.detector
    assert "nudity detector" in hold.describe()


def test_a_live_photo_is_held_by_its_clip_too(tmp_path):
    config = config_at(tmp_path)
    bank_a_head(config, "clip")

    hold = holds.read(config, ["still"], clips={"still": "clip"})["still"]

    assert hold.can_clear and "motion clip" in hold.describe()


def test_a_hold_an_earlier_cut_banked_is_named(tmp_path):
    config = config_at(tmp_path)
    banked = AudienceBank(open_store(), answerer="full|reader")
    banked.hold("bath", {"verdict": "do_not_show", "finding": "private_activity", "policy": "v17"})
    banked.flush()

    hold = holds.read(config, ["bath"])["bath"]

    assert hold.can_clear and not hold.detector
    assert "caption" in hold.describe()


def test_clearing_says_so_and_offers_no_second_clearance(tmp_path):
    config = config_at(tmp_path)
    bank_a_head(config, "beach")

    holds.clear_hold(config, "beach", via="web")
    hold = holds.read(config, ["beach"])["beach"]

    assert not hold.can_clear
    assert hold.describe().startswith("You cleared its hold")


def test_never_use_says_so_whatever_holds_it(tmp_path):
    config = config_at(tmp_path)

    holds.never_use(config, "calm", via="web")

    assert holds.read(config, ["calm"])["calm"].describe() == "You'll never use this picture."


def test_the_store_knows_a_live_photo_s_clip_without_being_told(tmp_path):
    config = config_at(tmp_path)
    bank_a_head(config, "clip")
    add_rows(
        holds.store_of(config),
        "annotation_assets",
        {"asset_id": "s", "live_photo_video_id": "clip"},
    )

    assert holds.read(config, ["s"])["s"].can_clear


def test_a_clearance_says_which_films_it_reaches(tmp_path):
    config = config_at(tmp_path)
    bank_a_head(config, "beach")

    holds.clear_hold(config, "beach", via="web", level="family")
    hold = holds.read(config, ["beach"])["beach"]

    assert hold.describe() == "You cleared its hold for the family (a nudity detector flagged it)."
    assert hold.decision == "cleared_family"
