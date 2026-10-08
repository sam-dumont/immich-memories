"""Country lookup caches misses too, and a changed key gets a fresh answer."""

import httpx
import pytest

from immich_memories import home_country
from immich_memories.config_loader import Config


@pytest.mark.parametrize("rows,expected", [([], None), ([{"country": "United States"}], "US")])
def test_country_results_are_reused_until_the_account_changes(monkeypatch, rows, expected):
    config = Config(
        immich={"url": "https://library.example", "api_key": "synthetic-key"},
        trips={"homebase_latitude": 1.0, "homebase_longitude": 1.0},
    )
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["headers"]["x-api-key"])
        return httpx.Response(200, json=rows, request=httpx.Request("GET", url))

    # WHY: replace the library HTTP boundary; exercise the actual fingerprint-keyed cache.
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(home_country, "_country_cache", {})
    assert home_country.known_home_country(config) == expected
    assert home_country.known_home_country(config) == expected
    assert calls == ["synthetic-key"]

    config.immich.api_key = "rotated-key"
    assert home_country.known_home_country(config) == expected
    assert calls == ["synthetic-key", "rotated-key"]
