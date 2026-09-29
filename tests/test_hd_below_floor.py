"""Below the memory a 4K software HEVC film needs, an automatic 4K becomes 1080p (#1527)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from immich_memories.processing import memory_budget
from immich_memories.processing.memory_budget import film_tier
from immich_memories.processing.output_canvas import resolve_output_canvas

GIB = 2**30


@pytest.mark.parametrize(
    ("gigabytes", "hardware_hevc", "explicit", "tier"),
    [
        (2, False, False, "1080p"),
        (2.5, False, False, "1080p"),
        (3, False, False, "4k"),
        (4, False, False, "4k"),
        (2, True, False, "4k"),
        (2.5, True, False, "4k"),
        (2, False, True, "4k"),
        (2.5, False, True, "4k"),
    ],
)
def test_only_a_software_hevc_box_below_the_floor_drops_an_automatic_4k(
    gigabytes, hardware_hevc, explicit, tier
):
    memory = int(gigabytes * GIB)
    assert film_tier("4k", memory=memory, hardware_hevc=hardware_hevc, explicit=explicit) == tier


def test_a_1080p_or_unknown_budget_is_left_alone():
    assert film_tier("1080p", memory=2 * GIB, hardware_hevc=False, explicit=False) == "1080p"
    assert film_tier("4k", memory=None, hardware_hevc=False, explicit=False) == "4k"


@pytest.fixture
def two_gigabyte_container(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text(f"{2 * GIB}\n")
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)


def _four_k_portrait_clips():
    return [SimpleNamespace(width=2160, height=3840) for _ in range(3)]


def test_an_automatic_4k_plan_renders_1080p_on_a_2_gb_software_box(two_gigabyte_container):
    canvas = resolve_output_canvas(
        resolution="auto",
        orientation=None,
        configured_resolution=(1920, 1080),
        clips=_four_k_portrait_clips(),
        hardware_hevc=lambda: False,
    )
    assert (canvas.width, canvas.height) == (1080, 1920)


def test_an_explicit_4k_request_wins_on_the_same_box(two_gigabyte_container):
    canvas = resolve_output_canvas(
        resolution="4k",
        orientation=None,
        configured_resolution=(1920, 1080),
        clips=_four_k_portrait_clips(),
        hardware_hevc=lambda: False,
    )
    assert (canvas.width, canvas.height) == (2160, 3840)


def test_a_hardware_encoder_keeps_4k_on_the_same_box(two_gigabyte_container):
    canvas = resolve_output_canvas(
        resolution="auto",
        orientation=None,
        configured_resolution=(1920, 1080),
        clips=_four_k_portrait_clips(),
        hardware_hevc=lambda: True,
    )
    assert (canvas.width, canvas.height) == (2160, 3840)


def test_preflight_says_the_film_renders_at_1080p(two_gigabyte_container):
    from immich_memories.config import Config
    from immich_memories.preflight_run import check_memory

    memory_budget.encode_lookahead.cache_clear()
    config = Config()
    config.hardware.enabled = False
    message = check_memory(config).message
    memory_budget.encode_lookahead.cache_clear()
    assert message.endswith(
        "4K needs about 3 GB for software HEVC; this box has 2.0 GB, so the film renders at 1080p"
    )


def test_an_explicit_4k_below_the_floor_is_kept_with_a_warning(two_gigabyte_container):
    from immich_memories.config import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_run import check_memory

    memory_budget.encode_lookahead.cache_clear()
    config = Config()
    config.hardware.enabled = False
    config.output.resolution = "4k"
    result = check_memory(config)
    memory_budget.encode_lookahead.cache_clear()
    assert result.status is CheckStatus.WARNING
    assert result.message.endswith(
        "4K set explicitly: software HEVC needs about 3 GB, this box has 2.0 GB, so the render "
        "may run out of memory; set resolution to auto or 1080p"
    )


def test_the_run_log_warns_once_about_an_explicit_4k(two_gigabyte_container, caplog):
    canvas = resolve_output_canvas(
        resolution="4k",
        orientation=None,
        configured_resolution=(1920, 1080),
        clips=_four_k_portrait_clips(),
        hardware_hevc=lambda: False,
    )
    assert (canvas.width, canvas.height) == (2160, 3840)
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == [
        "4K set explicitly: software HEVC needs about 3 GB, this box has 2.0 GB, so the render "
        "may run out of memory; set resolution to auto or 1080p"
    ]
