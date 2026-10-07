"""The auto-tier line is said once per answer, however often the config loads (#2244)."""

from __future__ import annotations

import logging
from unittest.mock import patch

from immich_memories.config_loader import Config
from immich_memories.config_tiers import _last_resolution, apply_tier


def _resolve(caplog, reason: str = "No GPU runtime") -> int:
    # WHY: inference_acceleration probes the machine; the answer is the input here.
    with (
        patch("immich_memories.config_tiers.inference_acceleration", return_value=(False, reason)),
        caplog.at_level(logging.INFO, logger="immich_memories.config_tiers"),
    ):
        apply_tier(Config())
    return sum("Tier auto resolved" in r.getMessage() for r in caplog.records)


def test_the_same_answer_is_logged_once_and_a_new_one_again(caplog):
    _last_resolution[0] = None

    assert [_resolve(caplog) for _ in range(5)] == [1, 1, 1, 1, 1], "five loads, one line"
    assert _resolve(caplog, "Now something else") == 2
