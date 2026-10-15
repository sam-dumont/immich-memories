"""A custom range asks for more film the longer it runs, up to the ten-minute cap (#2356)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.config.loader import Config
from tests.test_cli_smoke import _invoke


def _asked_length(start: str, end: str) -> float:
    """The length `generate --start --end` with no type and no duration plans the film for."""
    config = Config()
    config.immich.url = "http://immich:2283"
    config.immich.api_key = "test-key"
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get_photos_for_date_range.return_value = []
    # WHY: SyncImmichClient is the Immich HTTP client this CLI path would otherwise call.
    with (
        patch("immich_memories.api.immich.SyncImmichClient", return_value=client),
        # WHY: fetch_media wraps the Immich video-listing call this test must not make.
        patch(
            "immich_memories.cli.generate.fetch_media",
            return_value=([MagicMock(duration_seconds=10.0)], []),
        ),
        # WHY: the editorial run and render; this test reads only what it was asked for.
        patch(
            "immich_memories.cli.generate.run_pipeline_and_generate",
            return_value=(Path("dry-run-plan.mp4"), False, None),
        ) as run,
    ):
        result = _invoke(["generate", "--start", start, "--end", end, "--dry-run"], config=config)
    assert result.exit_code == 0, result.output
    return run.call_args.kwargs["preset_duration"]


@pytest.mark.feature("planning.long-range-length")
def test_a_five_year_range_asks_for_the_ten_minute_cap():
    assert _asked_length("2020-01-01", "2024-12-31") == 600.0


@pytest.mark.feature("planning.long-range-length")
def test_a_longer_range_never_asks_for_less_film():
    ends = ("2024-01-31", "2024-06-30", "2024-12-31", "2025-12-31", "2026-12-31", "2028-12-31")
    lengths = [_asked_length("2024-01-01", end) for end in ends]

    assert lengths == sorted(lengths)
    assert 60.0 <= lengths[0] < 65.0
    assert lengths[-1] == 600.0
