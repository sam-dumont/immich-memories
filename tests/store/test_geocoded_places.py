"""The reverse-geocode cache: one question per coordinate cell and language, on every backend."""

from __future__ import annotations

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
