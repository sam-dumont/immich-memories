"""Basic is the CPU tier; the retired `nas` name is refused, not silently mapped."""

import pytest
import yaml

from immich_memories.config_loader import Config

NAS_REFUSED = "tier 'nas' is now called 'basic': set tier: basic"


def test_basic_tier_has_the_cpu_only_contract():
    config = Config(tier="basic")
    assert config.tier == "basic"
    assert config.editorial.reader == "rules"
    assert config.editorial.preparation.tier == "no_captions"
    assert not config.editorial.detectors_enabled
    assert config.model_dump()["tier"] == "basic"


def test_nas_is_refused_directly():
    with pytest.raises(ValueError, match=NAS_REFUSED):
        Config(tier="nas")


@pytest.mark.parametrize("source", ["yaml", "saved", "env"])
def test_legacy_nas_is_refused_from_every_loader_source(tmp_path, monkeypatch, source):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"tier": "nas"} if source == "yaml" else {}))
    # WHY: the autouse path guard constructs Config during teardown, before monkeypatch undo.
    with monkeypatch.context() as invalid:
        if source == "env":
            invalid.setenv("IMMICH_MEMORIES_TIER", "nas")
        with pytest.raises(ValueError, match=NAS_REFUSED):
            Config.from_yaml(path, stored={"tier": "nas"} if source == "saved" else {})


def test_legacy_nas_is_refused_from_the_deployment_tier_env(tmp_path, monkeypatch):
    # WHY: the autouse path guard constructs Config during teardown, before monkeypatch undo.
    with monkeypatch.context() as invalid:
        invalid.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "nas")
        with pytest.raises(ValueError, match=NAS_REFUSED):
            Config.from_yaml(tmp_path / "missing.yaml", stored={})


def test_deployment_basic_preset_uses_the_basic_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "basic")
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.tier == "basic"
    assert config.editorial.preparation.tier == "no_captions"
    assert not config.inference.facts_base_url
