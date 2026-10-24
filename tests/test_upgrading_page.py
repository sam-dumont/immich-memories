"""The published upgrade page names every 1.0 security change and every new default film."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.config.models.automation import AutomationConfig

PAGE = (
    Path(__file__).resolve().parents[1] / "docs-site/docs/run/maintenance/upgrading.md"
).read_text(encoding="utf-8")
DETECTORS = (
    "detect_seasons",
    "detect_holidays",
    "detect_albums",
    "detect_person_monthly",
    "backfill_months",
)


@pytest.mark.feature("docs.upgrading-1-0")
def test_the_page_has_one_security_section_naming_each_change_and_its_fix():
    section = PAGE.split("## Security changes in 1.0")[1].split("\n## ")[0]

    for needle in ("immich.url", "immich.api_key", "auth.public_url", "421", "allowed_hosts"):
        assert needle in section
    assert "`/health`" in section
    assert "`null`" in section
    assert "4 MiB" in section
    assert "413" in section
    assert PAGE.count("## Security changes in 1.0") == 1


@pytest.mark.feature("docs.upgrading-1-0")
def test_every_default_on_detector_is_listed_with_a_key_that_exists():
    fields = AutomationConfig.model_fields

    for key in DETECTORS:
        assert fields[key].default is True, key
        assert f"`{key}`" in PAGE, key


@pytest.mark.feature("docs.upgrading-1-0")
def test_the_settings_that_moved_to_the_file_are_listed():
    section = PAGE.split("## Security changes in 1.0")[1].split("\n## ")[0]

    for key in (
        "render.worker_base_url",
        "render.worker_token",
        "llm.local_server",
        "triage.encoder",
        "free_text.wordnet",
        "editorial.laya_checkpoint",
        "editorial.preparation.detector_python",
        "editorial.preparation.detector_cache_dir",
        "editorial.preparation.marqo_onnx",
    ):
        assert f"`{key}`" in section, key


@pytest.mark.feature("docs.upgrading-1-0")
def test_every_key_that_left_the_config_says_what_its_value_does_until_2_0():
    """The table once said "fixed" for knobs the code still reads; each row now matches its kind."""
    from immich_memories.config.unsupported import IGNORED, INTERNAL, MERGED, MOVED, TIER_OWNED

    section = PAGE.split("### Settings that left the config")[1].split("\n### ")[0]
    until = {
        row.split(" | ")[0].strip("| `"): row.split(" | ")[1]
        for row in section.splitlines()
        if row.startswith("| `")
    }
    expected = dict.fromkeys(TIER_OWNED, "ignored: `tier` sets it")
    expected |= dict.fromkeys((*INTERNAL, *MERGED), "your value still applies")
    expected |= {key: f"applied to `{new}`" for key, new in MOVED.items()}
    expected |= dict.fromkeys(IGNORED, "ignored")

    for key, start in expected.items():
        assert until.get(key, "").startswith(start), key
