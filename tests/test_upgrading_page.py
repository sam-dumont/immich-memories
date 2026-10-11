"""The published upgrade page names every 1.0 security change and every new default film."""

from __future__ import annotations

from pathlib import Path

from immich_memories.config_models_automation import AutomationConfig

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


def test_the_page_has_one_security_section_naming_each_change_and_its_fix():
    section = PAGE.split("## Security changes in 1.0")[1].split("\n## ")[0]

    for needle in ("immich.url", "immich.api_key", "auth.public_url", "421", "allowed_hosts"):
        assert needle in section
    assert "`/health`" in section
    assert "`null`" in section
    assert "4 MiB" in section
    assert "413" in section
    assert PAGE.count("## Security changes in 1.0") == 1


def test_every_default_on_detector_is_listed_with_a_key_that_exists():
    fields = AutomationConfig.model_fields

    for key in DETECTORS:
        assert fields[key].default is True, key
        assert f"`{key}`" in PAGE, key


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
