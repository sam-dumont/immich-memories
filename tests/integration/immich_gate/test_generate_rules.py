"""Real-Immich gate: `generate --no-render` picks a cut from the fixture month on the rules tier.

The NAS tier uses rules and inexpensive CPU picture models. The gate fetches
the pinned artifacts before selection; no caption or prose model is used.
"""

from __future__ import annotations

from tests.integration.immich_fixtures import requires_immich
from tests.integration.immich_gate.gate_cli import run_cli

pytestmark = [requires_immich]


def test_rules_tier_selection_over_the_fixture_month_picks_a_cut(tmp_path):
    trace = tmp_path / "selection-trace.txt"
    result = run_cli(
        "generate",
        # A standard memory type: rules refuse a free-form custom range.
        "--memory-type",
        "monthly_highlights",
        "--year",
        "2024",
        "--month",
        "6",
        "--include-photos",
        "--no-music",
        "--no-render",
        "--quiet",
        "--trace-selection",
        str(trace),
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output[-4000:]
    assert "Selection complete; no video was created" in output, output[-4000:]
    assert trace.exists(), output[-4000:]
    assert trace.stat().st_size > 0


def test_on_this_day_looks_back_to_the_same_day_a_year_earlier(tmp_path):
    result = run_cli(
        "generate",
        "--memory-type",
        "on_this_day",
        # The fixture's busiest day is 15 June 2024, held again on 15 June 2023.
        "--day",
        "2025-06-15",
        "--years-back",
        "2",
        "--include-photos",
        "--no-music",
        "--no-render",
        "--quiet",
        "--trace-selection",
        str(tmp_path / "selection-trace.txt"),
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output[-4000:]
    assert "Selection complete; no video was created" in output, output[-4000:]


def test_the_christmas_holiday_finds_its_two_years(tmp_path):
    result = run_cli(
        "generate",
        "--memory-type",
        "holiday",
        "--holiday",
        "12-25",
        "--year",
        "2024",
        "--years-back",
        "1",
        "--include-photos",
        "--no-music",
        "--no-render",
        "--quiet",
        "--trace-selection",
        str(tmp_path / "selection-trace.txt"),
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output[-4000:]
    assert "Selection complete; no video was created" in output, output[-4000:]


def test_a_year_with_no_trips_exits_one():
    result = run_cli("generate", "--memory-type", "trip", "--year", "2010", "--no-render")

    assert result.returncode == 1, (result.stdout + result.stderr)[-4000:]
