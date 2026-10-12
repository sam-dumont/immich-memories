"""Forget what the process learned about FFmpeg, so no test inherits another's stub."""

from __future__ import annotations


def forget_ffmpeg_capabilities() -> None:
    """Drop every cached answer about the FFmpeg on PATH.

    Each is cached for the process. A test that stubs `subprocess.run` leaves its stub's
    answer behind: a zscale filter the runner's build lacks, or a version of 0 that picks
    the `-filter_complex_script` spelling FFmpeg 9 removed (#2456).
    """
    from immich_memories.processing import ffmpeg_runner, hdr_utilities

    hdr_utilities._zscale_cache = None
    hdr_utilities._sdr_pq_fast_gamma_qualified.cache_clear()
    ffmpeg_runner.ffmpeg_major_version.cache_clear()
