"""Links shown to a person use immich.public_url; the server's own calls keep immich.url."""

from __future__ import annotations

import pytest

from immich_memories.config_loader import Config

INTERNAL = "http://immich.immich.svc.cluster.local:2283"
PUBLIC = "https://photos.example.org/"


def _config(**immich: str) -> Config:
    return Config(immich={"url": INTERNAL, "api_key": "k", **immich})


def test_links_fall_back_to_the_server_url_without_a_public_one() -> None:
    config = _config()

    assert config.immich.asset_url("a1") == f"{INTERNAL}/photos/a1"
    assert config.immich.person_url("p1") == f"{INTERNAL}/people/p1"


def test_links_use_the_public_url_and_the_server_url_stays_for_calls() -> None:
    config = _config(public_url=PUBLIC)

    assert config.immich.asset_url("a1") == "https://photos.example.org/photos/a1"
    assert config.immich.person_url("p1") == "https://photos.example.org/people/p1"
    assert config.immich.url == INTERNAL


def test_a_public_url_alone_still_gives_a_link_but_no_url_means_no_link() -> None:
    assert Config(immich={"public_url": PUBLIC}).immich.asset_url("a1")
    assert Config().immich.asset_url("a1") is None


def test_a_public_url_must_be_an_http_address() -> None:
    with pytest.raises(ValueError, match="http"):
        _config(public_url="photos.example.org")
