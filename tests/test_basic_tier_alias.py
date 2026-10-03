"""Basic is the CPU tier; old deployment and saved values remain readable."""

import pytest
import yaml

from immich_memories.config_loader import Config


@pytest.mark.parametrize("value", ["basic", "nas"])
def test_basic_and_legacy_nas_have_one_canonical_contract(value):
    config = Config(tier=value)
    assert config.tier == "basic"
    assert config.editorial.reader == "rules"
    assert config.editorial.preparation.tier == "no_captions"
    assert not config.editorial.detectors_enabled
    assert config.model_dump()["tier"] == "basic"


@pytest.mark.parametrize("source", ["yaml", "saved", "env"])
def test_legacy_nas_survives_real_loader_sources(tmp_path, monkeypatch, source):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"tier": "nas"} if source == "yaml" else {}))
    if source == "env":
        monkeypatch.setenv("IMMICH_MEMORIES_TIER", "nas")
    config = Config.from_yaml(path, stored={"tier": "nas"} if source == "saved" else {})
    assert config.tier == "basic"
    assert config.editorial.reader == "rules"


def test_deployment_basic_preset_uses_the_basic_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "basic")
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.tier == "basic"
    assert config.editorial.preparation.tier == "no_captions"
    assert not config.inference.facts_base_url
