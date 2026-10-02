"""Configured service URLs keep ordinary private networks working."""

import pytest
from pydantic import ValidationError

from immich_memories.config_loader import Config
from immich_memories.settings_store import nest_dotted


@pytest.mark.parametrize(
    "key",
    [
        "llm.base_url",
        "title_llm.base_url",
        "editorial.preparation.caption_base_url",
        "network.geocoding_url",
        "musicgen.base_url",
        "ace_step.api_url",
        "render.worker_base_url",
        "inference.facts_base_url",
    ],
)
@pytest.mark.parametrize("host", ["169.254.169.254", "[fe80::1]", "[::ffff:169.254.1.1]"])
def test_link_local_service_urls_require_an_operator_override(key, host, monkeypatch):
    monkeypatch.delenv("IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS", raising=False)
    values = nest_dotted({key: f"https://{host}/"})
    with pytest.raises(ValidationError, match="link-local"):
        Config(**values)


@pytest.mark.parametrize("url", ["json://169.254.1.2", "jsons://[fe80::1]", "not-a-service://host"])
def test_notification_urls_use_apprise_schemes_and_the_address_policy(url, monkeypatch):
    monkeypatch.delenv("IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS", raising=False)
    with pytest.raises(ValidationError, match="notifications.urls"):
        Config(notifications={"urls": [url]})


@pytest.mark.parametrize("host", ["localhost", "192.168.1.2", "10.0.0.5", "[fd00::1]"])
def test_private_services_stay_available(host):
    assert Config(tier="nas", inference={"facts_base_url": f"http://{host}"}).inference.enabled


def test_only_the_environment_can_allow_link_local_urls(monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS", "true")
    assert Config(tier="nas", inference={"facts_base_url": "http://169.254.1.1"}).inference.enabled
    with pytest.raises(ValidationError):
        Config(llm={"base_url": "file:///tmp/model"})


def test_settings_refuse_a_link_local_url_without_saving_it(tmp_path, monkeypatch):
    from tests.test_web_settings import _settings_client

    client, _ = _settings_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/settings", json={"values": {"inference.facts_base_url": "http://169.254.1.1"}}
    )
    assert response.status_code == 422
    rows = client.get("/api/v1/settings").json()["sections"]
    setting = next(
        row
        for section in rows
        for row in section["settings"]
        if row["key"] == "inference.facts_base_url"
    )
    assert setting["value"] == ""


def test_apprise_custom_schemes_are_supported():
    assert Config(
        notifications={"urls": ["json://192.168.1.2", "mailto://user:password@example.com"]}
    ).notifications.urls


def test_apprise_token_urls_do_not_use_http_port_rules():
    assert Config(
        notifications={"urls": ["tgram://123456:abcdefghijklmnop/12345"]}
    ).notifications.urls
