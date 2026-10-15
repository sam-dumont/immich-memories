"""`model_variant: auto` picks the ACE-Step DiT from the memory this host has."""

from __future__ import annotations

import pytest

from immich_memories.audio.generators.ace_step_model_choice import (
    HostMemory,
    choose_model_variant,
    resolve_model_variant,
)
from immich_memories.config.loader import Config

GIB = 1024**3


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (HostMemory(unified_gib=128.0), "xl-turbo"),
        (HostMemory(unified_gib=64.0), "xl-turbo"),
        (HostMemory(unified_gib=48.0), "turbo"),
        (HostMemory(unified_gib=16.0), "turbo"),
        (HostMemory(gpu_gib=24.0), "xl-turbo"),
        # A 16 GB card reports a little under 16 GiB: the driver keeps its share.
        (HostMemory(gpu_gib=16376 / 1024), "xl-turbo"),
        (HostMemory(gpu_gib=12.0), "turbo"),
        (HostMemory(gpu_gib=8.0), "turbo"),
        (HostMemory(), "turbo"),
    ],
)
def test_auto_picks_xl_only_where_the_memory_holds_it(host, expected):
    assert choose_model_variant("auto", host) == expected


@pytest.mark.parametrize("written", ["turbo", "base", "acestep-v15-xl-turbo", "xl-turbo"])
def test_a_variant_the_user_wrote_wins_on_any_host(written):
    assert choose_model_variant(written, HostMemory(unified_gib=128.0)) == written
    assert choose_model_variant(written, HostMemory(gpu_gib=4.0)) == written


def test_auto_reads_unified_memory_on_a_mac(monkeypatch):
    # WHY: the host probe is the boundary; a CI runner is neither a 128 GB Mac nor a GPU box.
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_model_choice._unified_memory_gib",
        lambda: 128.0,
    )

    assert resolve_model_variant("auto") == "xl-turbo"


def test_auto_reads_the_gpu_on_linux(monkeypatch):
    # WHY: nvidia-smi is the boundary; the runner has no NVIDIA card.
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_model_choice._gpu_memory_mb", lambda: 8192
    )

    assert resolve_model_variant("auto") == "turbo"


def test_the_default_config_is_auto_and_a_written_turbo_stays_turbo(tmp_path):
    assert Config().ace_step.model_variant == "auto"
    written = tmp_path / "config.yaml"
    written.write_text("advanced:\n  ace_step:\n    model_variant: turbo\n")

    assert Config.from_yaml(written, stored={}).ace_step.model_variant == "turbo"
