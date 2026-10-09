"""Completed whole-day history keeps distinct scopes and partial-day windows apart."""

import pytest

from immich_memories.automation.candidates import completed_memory_key_aliases


@pytest.mark.parametrize(
    "suffix",
    ["", "kid a", "kid a,kid b:anniversary-10", "kid a:people-abc123"],
)
def test_whole_day_alias_preserves_the_complete_memory_scope(suffix):
    dated = f"monthly_highlights:2025-04-01:2025-04-30:{suffix}"
    timed = f"monthly_highlights:2025-04-01T00:00:00:2025-04-30T23:59:59:{suffix}"

    assert completed_memory_key_aliases({dated, timed}) == {dated, timed}
    assert completed_memory_key_aliases({dated}) == {dated, timed}
    assert completed_memory_key_aliases({timed}) == {dated, timed}


@pytest.mark.parametrize(
    "key",
    [
        "opaque-legacy-key",
        "trip:2025-04-01T09:00:00:2025-04-30T23:59:59:kid a",
        "trip:2025-04-01T00:00:00:2025-04-30T12:00:00:kid a",
        "trip:2025-04-01T00:00:00+02:00:2025-04-30T23:59:59+02:00:kid a",
        "trip:2025-04-01:2025-04-30T23:59:59:kid a",
        "trip:2025-04-01T00:00:00:2025-04-30:kid a",
        "trip:2025-02-30:2025-04-30:kid a",
    ],
)
def test_partial_day_and_unknown_history_never_claim_a_whole_day_window(key):
    assert completed_memory_key_aliases({key}) == {key}
