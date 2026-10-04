"""The reverse-geocode cache: one question per coordinate cell and language, on every backend."""

from __future__ import annotations

import pytest

from immich_memories.analysis.place_geocoder import PlaceGeocoder

WILRIJK = {"suburb": "Wilrijk", "city": "Antwerpen", "country": "België"}


class _Nominatim:
    """Stands in for the HTTP call and counts the cells it was asked about."""

    def __init__(self, answer: dict[str, str] | None = WILRIJK) -> None:
        self.answer = answer
        self.asked: list[tuple[float, float]] = []

    def __call__(self, latitude: float, longitude: float) -> dict[str, str] | None:
        self.asked.append((latitude, longitude))
        return self.answer


def _refuse(*_args: float) -> dict[str, str]:
    raise AssertionError("the cache should have answered")


def test_two_pictures_in_one_cell_ask_once(store):
    nominatim = _Nominatim()
    places = PlaceGeocoder(store, "nl", nominatim)

    # About 200 m apart: one cell once rounded.
    first = places.address(51.1682, 4.3931)
    second = places.address(51.1695, 4.3942)

    assert first == second == WILRIJK
    assert nominatim.asked == [(51.17, 4.39)]


def test_the_next_render_reads_the_cell_from_the_store(store):
    PlaceGeocoder(store, "nl", _Nominatim()).address(51.17, 4.39)

    assert PlaceGeocoder(store, "nl", _refuse).address(51.17, 4.39) == WILRIJK


def test_old_settlement_answers_and_swallowed_failures_are_refetched(store):
    from immich_memories.db import now_db
    from immich_memories.db.tables import geocoded_places

    with store.begin() as connection:
        connection.execute(
            geocoded_places.insert(),
            [
                {
                    "cell": "50.88,4.34",
                    "language": "fr",
                    "address": {"village": "Mutsaard"},
                    "fetched_at": now_db(),
                },
                {"cell": "50.88,4.35", "language": "fr", "address": {}, "fetched_at": now_db()},
            ],
        )
    fresh = _Nominatim({"suburb": "Laeken", "city": "Bruxelles"})
    places = PlaceGeocoder(store, "fr", fresh)

    assert places.address(50.88, 4.34)["suburb"] == "Laeken"
    assert places.address(50.88, 4.35)["suburb"] == "Laeken"
    assert len(fresh.asked) == 2


def test_another_language_is_another_question(store):
    PlaceGeocoder(store, "nl", _Nominatim()).address(51.17, 4.39)
    french = _Nominatim({"suburb": "Wilrijk", "city": "Anvers", "country": "Belgique"})

    assert PlaceGeocoder(store, "fr", french).address(51.17, 4.39)["city"] == "Anvers"
    assert len(french.asked) == 1


def test_a_cell_nobody_can_name_is_not_asked_twice(store):
    PlaceGeocoder(store, "en", _Nominatim(None)).address(0.0, -30.0)

    assert PlaceGeocoder(store, "en", _refuse).address(0.0, -30.0) == {}


def test_an_outage_answers_nothing_keeps_nothing_and_stops_asking(store):
    calls: list[float] = []

    def down(latitude: float, _longitude: float) -> dict[str, str]:
        calls.append(latitude)
        raise OSError("service unavailable")

    places = PlaceGeocoder(store, "en", down)

    assert places.address(51.17, 4.39) == {}
    assert places.address(48.86, 2.35) == {}
    assert calls == [51.17]
    later = _Nominatim()
    assert PlaceGeocoder(store, "en", later).address(51.17, 4.39) == WILRIJK
    assert later.asked == [(51.17, 4.39)]


def test_a_geopy_timeout_is_not_cached_as_an_empty_place(store, monkeypatch):
    from geopy.exc import GeocoderTimedOut

    from immich_memories.analysis.place_geocoder import nominatim_fetch

    class TimedOutNominatim:
        def __init__(self, **_kwargs):
            pass

        def reverse(self, *_args, **_kwargs):
            raise GeocoderTimedOut("test timeout")

    # Replace the external geocoder, keeping the real rate limiter and persistence path.
    monkeypatch.setattr("geopy.geocoders.Nominatim", TimedOutNominatim)
    assert PlaceGeocoder(store, "fr", nominatim_fetch("fr")).address(50.88, 4.34) == {}

    recovered = _Nominatim({"suburb": "Laeken", "city": "Bruxelles"})
    assert PlaceGeocoder(store, "fr", recovered).address(50.88, 4.34)["suburb"] == "Laeken"
    assert recovered.asked == [(50.88, 4.34)]


@pytest.mark.parametrize(
    "user_language,requested_languages",
    [("fr", "fr"), ("nl", "nl"), ("ja", "ja"), ("pt-BR", "pt-BR,pt"), ("en", "en")],
)
def test_geocoding_prefers_the_users_language_before_any_fallback(
    monkeypatch, user_language, requested_languages
):
    from types import SimpleNamespace

    from immich_memories.analysis.place_geocoder import nominatim_fetch

    requests = []

    class Nominatim:
        def __init__(self, **_kwargs):
            pass

        def reverse(self, query, **kwargs):
            requests.append((query, kwargs))
            return SimpleNamespace(raw={"address": {"city": "User-language city"}})

    monkeypatch.setattr("geopy.geocoders.Nominatim", Nominatim)

    assert nominatim_fetch(user_language)(35.17, 33.36) == {"city": "User-language city"}
    assert requests == [("35.17, 33.36", {"zoom": 16, "language": requested_languages})]


def test_old_single_language_answers_do_not_mask_translated_names(store):
    from immich_memories.db import now_db
    from immich_memories.db.tables import geocoded_places

    with store.begin() as connection:
        connection.execute(
            geocoded_places.insert(),
            {
                "cell": "z16:34.74,32.43",
                "language": "fr",
                "address": {"town": "Γεροσκήπου"},
                "fetched_at": now_db(),
            },
        )
    translated = _Nominatim({"town": "Yeroskipou"})

    assert PlaceGeocoder(store, "fr", translated).address(34.74, 32.43) == {"town": "Yeroskipou"}
    assert translated.asked == [(34.74, 32.43)]
