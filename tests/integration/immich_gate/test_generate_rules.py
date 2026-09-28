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
