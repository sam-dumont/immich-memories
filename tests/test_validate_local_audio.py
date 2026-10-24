"""Behavior tests for the local audio validation utility."""

import pytest
from scripts.validate_local_audio import build_acestep_config, bundled_reason

from immich_memories.audio.generators.ace_step_model_choice import HostMemory


@pytest.mark.parametrize("quality, planner", [("low", None), ("high", "4B")])
def test_both_profiles_let_generation_choose_the_model_films_use(quality, planner):
    """`auto` is the setting films run with, so the check takes the same XL decision."""
    config = build_acestep_config(quality)

    assert config.mode == "lib"
    assert config.model_variant == "auto"
    assert (config.lm_model_size if config.use_lm else None) == planner


@pytest.mark.parametrize(
    "host",
    [HostMemory(unified_gib=32), HostMemory(gpu_gib=12), HostMemory()],
)
def test_a_host_below_the_xl_bar_is_told_films_play_the_bundled_library(host):
    reason = bundled_reason(host)

    assert reason is not None
    assert "bundled library" in reason


@pytest.mark.parametrize("host", [HostMemory(unified_gib=64), HostMemory(gpu_gib=16)])
def test_an_xl_host_runs_the_check(host):
    assert bundled_reason(host) is None
