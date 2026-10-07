"""The keys and categories rc.6 adds to automation (#2227-#2232)."""

from __future__ import annotations

from datetime import date

from immich_memories.automation.candidates import CandidateCategory, make_manual_memory_key


def test_a_hand_made_month_film_and_the_automatic_key_are_the_same_string():
    # What `generate --memory-type monthly_highlights --month 6 --year 2025` records.
    recorded_by_a_manual_run = "monthly_highlights:2025-06-01T00:00:00:2025-06-30T23:59:59:"

    key = make_manual_memory_key("monthly_highlights", date(2025, 6, 1), date(2025, 6, 30))

    assert key == recorded_by_a_manual_run


def test_a_person_month_key_names_the_person_in_lower_case():
    key = make_manual_memory_key(
        "monthly_highlights", date(2025, 6, 1), date(2025, 6, 30), ["Kid A"]
    )

    assert key == "monthly_highlights:2025-06-01T00:00:00:2025-06-30T23:59:59:kid a"


def test_every_new_detector_has_its_own_category():
    names = {c.value for c in CandidateCategory}

    assert {"season", "holiday", "album", "backfill", "person_monthly"} <= names


def test_every_new_detector_is_on_by_default_and_shared_albums_are_not():
    from immich_memories.config_models_automation import AutomationConfig

    config = AutomationConfig()

    assert config.detect_seasons and config.detect_holidays and config.detect_albums
    assert config.detect_person_monthly and config.backfill_months
    assert config.extra_holidays == []
    assert config.include_shared_albums is False


def test_extra_holidays_are_written_month_day_then_a_name():
    import pytest

    from immich_memories.config_models_automation import AutomationConfig

    assert AutomationConfig(extra_holidays=["12-06: Saint Nicholas"]).extra_holidays == [
        "12-06: Saint Nicholas"
    ]
    for bad in ("Saint Nicholas", "12-06", "13-40: Nowhere", "02-30: Never"):
        with pytest.raises(ValueError, match="extra_holidays"):
            AutomationConfig(extra_holidays=[bad])
