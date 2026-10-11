"""Stage-1 gather math: era shares (person annotation layer)."""

from datetime import date


def test_era_day_shares_lists_only_eras_the_library_can_speak_for() -> None:
    """One row per era with data; an era the library never photographed says nothing."""
    from immich_memories.people.gather import COVID_ERA, Era, era_day_shares

    library_days = {date(2020, 4, n) for n in range(1, 11)}
    person_days = {date(2020, 4, 2), date(2020, 4, 5), date(2020, 4, 9)}
    silent_era = Era("pre-library", start=date(1990, 1, 1), end=date(1999, 12, 31))

    assert era_day_shares(person_days, library_days, eras=(COVID_ERA, silent_era)) == (
        ("covid", 0.3),
    )
