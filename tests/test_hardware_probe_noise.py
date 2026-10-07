"""A hardware probe that fails is the normal answer on most hosts, not news."""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import patch

from immich_memories.processing.hardware import _probe_ffmpeg_encode

RAW_STDERR = (
    "[AVHWDeviceContext @ 0x1] No VA display found for device /dev/dri/renderD128.\n"
    "Device creation failed: -22.\n"
    "Error parsing global options: Invalid argument\n"
)


def _failing_probe(encoder: str, upload: str):
    # WHY: ffmpeg is the external boundary; this host's real hardware must not decide the test.
    failed = subprocess.CompletedProcess([], 1, stdout="", stderr=RAW_STDERR)
    with patch("immich_memories.processing.hardware.subprocess.run", return_value=failed):
        return _probe_ffmpeg_encode(["-c:v", encoder], upload=upload)


def test_failing_probe_stderr_stays_out_of_the_console(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="immich_memories.processing.hardware"):
        assert _failing_probe("h264_vaapi", "vaapi") is False

    assert "Error parsing global options" not in caplog.text
    assert "No VA display" not in caplog.text


def test_failing_probe_stderr_is_kept_for_debugging(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="immich_memories.processing.hardware"):
        _failing_probe("h264_vaapi", "vaapi")

    assert "Error parsing global options" in caplog.text


def test_the_same_advice_is_given_once_however_many_probes_fail(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="immich_memories.processing.hardware"):
        for encoder in ("h264_vaapi", "hevc_vaapi", "h264_qsv", "hevc_qsv"):
            _failing_probe(encoder, "vaapi")

    assert caplog.text.count("libva could not open a device") == 1


def test_the_libva_advice_is_info_on_the_basic_tier_and_a_warning_elsewhere(caplog) -> None:
    from immich_memories.processing import hardware
    from immich_memories.tracking.timing import collecting

    levels = {}
    for tier in ("basic", "gpu"):
        hardware._advice_given.clear()
        caplog.clear()
        with collecting() as collected, caplog.at_level(logging.INFO):
            collected.diagnostics["tier"] = tier
            _failing_probe("h264_vaapi", "vaapi")
        levels[tier] = [r.levelno for r in caplog.records if "libva could not" in r.getMessage()]

    assert levels == {"basic": [logging.INFO], "gpu": [logging.WARNING]}
