"""The gate library holds a second dated year on the busiest day, and a 25 December set (#2089)."""

from __future__ import annotations

from pathlib import Path

from tests.integration.immich_gate import media


def test_the_echo_set_falls_on_the_busiest_day_a_year_earlier():
    echo = [f for f in media.dated_files(Path("/gate")) if f.path.name.startswith("GATE_ECHO")]

    assert len(echo) == media.ECHO_COUNT
    assert {(f.taken_at.year, f.taken_at.month, f.taken_at.day) for f in echo} == {
        (media.ECHO_YEAR, 6, 15)
    }


def test_christmas_is_held_in_two_years():
    xmas = [f for f in media.dated_files(Path("/gate")) if f.path.name.startswith("GATE_XMAS")]

    assert {f.taken_at.year for f in xmas} == set(media.CHRISTMAS_YEARS)
    assert {(f.taken_at.month, f.taken_at.day) for f in xmas} == {(12, 25)}
    assert len(xmas) == media.CHRISTMAS_COUNT * len(media.CHRISTMAS_YEARS)


def test_every_dated_file_has_its_own_name_and_capture_time():
    files = media.dated_files(Path("/gate"))

    assert len({f.path for f in files}) == len(files)
    assert len({f.taken_at for f in files}) == len(files)
