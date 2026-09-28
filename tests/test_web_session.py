"""What the client learns about this browser's session and the switches the server offers."""

from __future__ import annotations

import pytest

from immich_memories.config_loader import Config
from tests.web_server_fixtures import server_client


@pytest.mark.parametrize("offered", [False, True])
def test_the_demo_switch_is_offered_only_where_the_config_turns_it_on(monkeypatch, offered):
    client = server_client(monkeypatch, Config(server={"enable_demo_mode": offered}))

    assert client.get("/api/v1/session").json()["demo_mode_offered"] is offered


def test_a_music_preview_is_offered_only_with_a_music_generator(monkeypatch):
    plain = server_client(monkeypatch, Config())
    assert plain.get("/api/v1/session").json()["music_preview_offered"] is False

    generating = server_client(monkeypatch, Config(musicgen={"enabled": True}))
    assert generating.get("/api/v1/session").json()["music_preview_offered"] is True
