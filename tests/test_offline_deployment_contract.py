"""Offline examples constrain destinations and load their feature overrides correctly."""

from pathlib import Path

import yaml

from immich_memories.config_loader import load_config
from immich_memories.preflight_network import outside_call_checks

ROOT = Path(__file__).resolve().parents[1]


def test_offline_runtime_overrides_disable_saved_outbound_features(tmp_path, monkeypatch):
    compose = yaml.safe_load((ROOT / "deploy/offline/docker-compose.yml.example").read_text())
    assert compose["services"]["immich-memories"]["ports"] == ["127.0.0.1:22830:8080"]
    env = compose["services"]["immich-memories"]["environment"]
    assert env["IMMICH_MEMORIES_TIER"] == "basic"
    source = tmp_path / "config.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "network": {"geocoding": True, "map_tiles": True},
                "advanced": {
                    "llm": {"enabled": True},
                    "render": {"worker_base_url": "https://render.example.com"},
                    "inference": {"facts_base_url": "https://inference.example.com"},
                    "editorial": {
                        "preparation": {"caption_provider": "llm", "tier": "full"},
                        "laya_audience": True,
                        "detectors_enabled": True,
                    },
                    "ace_step": {"enabled": True},
                    "musicgen": {"enabled": True},
                    "notifications": {"urls": ["ntfys://example.com/topic"]},
                },
            }
        )
    )
    for name, value in env.items():
        if "${" not in str(value):
            monkeypatch.setenv(name, str(value))

    config = load_config(source)

    assert config.tier == "basic"
    assert not config.llm.enabled
    assert not config.render.enabled
    assert not config.inference.enabled
    assert not config.ace_step.enabled
    assert not config.musicgen.enabled
    assert config.notifications.urls == []
    assert not config.editorial.preparation.allow_model_downloads
    assert config.editorial.preparation.caption_provider == "smolvlm"
    assert config.editorial.preparation.tier == "no_captions"
    assert not config.editorial.detectors_enabled
    assert not config.editorial.laya_audience
    assert outside_call_checks(config) == []
    assert str(config.triage.encoder_path) == "/models/triage/dinov2-small.onnx"
    assert str(config.free_text.wordnet_path) == "/models/wordnet/wordnet.zip"


def test_offline_policy_replaces_base_and_every_rule_has_a_destination():
    policy = yaml.safe_load((ROOT / "deploy/offline/networkpolicy.yaml.example").read_text())
    base = yaml.safe_load((ROOT / "deploy/kubernetes/base/networkpolicy.yaml").read_text())
    assert policy["metadata"] == {
        "name": base["metadata"]["name"],
        "namespace": base["metadata"]["namespace"],
    }
    for rule in policy["spec"]["egress"]:
        assert rule["to"]
        for peer in rule["to"]:
            if "ipBlock" in peer:
                assert peer["ipBlock"]["cidr"].endswith("/32")
            if "namespaceSelector" in peer:
                assert peer["podSelector"]["matchLabels"]


def test_offline_policy_selects_in_cluster_immich_by_pod_not_by_address():
    # An in-cluster Immich behind a LoadBalancer IP is matched on its backend pod by some CNIs
    # (Cilium), so an ipBlock for that IP never matches and the app loses Immich.
    policy = yaml.safe_load((ROOT / "deploy/offline/networkpolicy.yaml.example").read_text())
    immich_rules = [
        rule
        for rule in policy["spec"]["egress"]
        if any(port["port"] == 2283 for port in rule["ports"])
    ]
    assert len(immich_rules) == 1
    (peer,) = immich_rules[0]["to"]
    assert "ipBlock" not in peer
    assert peer["namespaceSelector"] and peer["podSelector"]["matchLabels"]
