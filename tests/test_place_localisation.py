"""A French film says Chypre, not Cyprus."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from immich_memories.i18n_places import localise_country, localise_place, place_label


class TestCountryNames:
    """CLDR territory names, offline, with everything unknown left alone."""

    @pytest.mark.parametrize(
        ("english", "locale", "expected"),
        [
            ("Cyprus", "fr", "Chypre"),
            ("Belgium", "nl", "België"),
            ("Italy", "fr", "Italie"),
            ("Cyprus", "en", "Cyprus"),
            ("Middle Earth", "fr", "Middle Earth"),
            ("Cyprus", "not-a-locale", "Cyprus"),
        ],
    )
    def test_names(self, english: str, locale: str, expected: str) -> None:
        assert localise_country(english, locale) == expected

    def test_only_the_country_part_of_a_label_moves(self) -> None:
        assert localise_place("Nicosia, Cyprus", "fr") == "Nicosia, Chypre"

    def test_a_bare_country_still_moves(self) -> None:
        assert localise_place("Cyprus", "fr") == "Chypre"

    def test_nothing_stays_nothing(self) -> None:
        assert localise_place(None, "fr") is None

    def test_a_label_is_city_then_localised_country(self) -> None:
        assert place_label("Nicosia", "Cyprus", "fr") == "Nicosia, Chypre"
        assert place_label(None, "Cyprus", "fr") == "Chypre"
        assert place_label("Nicosia", None, "fr") == "Nicosia"
        assert place_label(None, None, "fr") is None


class TestTheFilmReadsTheseNames:
    """The four places a viewer meets a country name."""

    def test_the_trip_title_localises_the_country(self) -> None:
        from immich_memories.titles._trip_titles import generate_trip_title

        title = generate_trip_title("Cyprus", date(2024, 7, 1), date(2024, 7, 10), locale="fr")

        assert "À CHYPRE" in title

    @pytest.mark.parametrize(
        ("place", "expected"),
        [
            # A ratchet render read "DEUX SEMAINES À ITALIE" (#1101).
            ("Italy", "DEUX SEMAINES EN ITALIE"),
            ("Iran", "DEUX SEMAINES EN IRAN"),
            ("Portugal", "DEUX SEMAINES AU PORTUGAL"),
            ("Mexico", "DEUX SEMAINES AU MEXIQUE"),
            ("United States", "DEUX SEMAINES AUX ÉTATS-UNIS"),
            ("Netherlands", "DEUX SEMAINES AUX PAYS-BAS"),
            ("Cyprus", "DEUX SEMAINES À CHYPRE"),
            ("Lisbon, Portugal", "DEUX SEMAINES À LISBON, PORTUGAL"),
        ],
    )
    def test_a_french_trip_title_takes_the_country_s_own_preposition(
        self, place: str, expected: str
    ) -> None:
        from immich_memories.titles._trip_titles import generate_trip_title

        title = generate_trip_title(place, date(2024, 7, 1), date(2024, 7, 14), locale="fr")

        assert title == f"{expected}, JUILLET 2024"

    def test_an_english_trip_title_keeps_in(self) -> None:
        from immich_memories.titles._trip_titles import generate_trip_title

        title = generate_trip_title("Italy", date(2024, 7, 1), date(2024, 7, 14), locale="en")

        assert title == "TWO WEEKS IN ITALY, JULY 2024"

    def test_a_clip_overlay_localises_the_country_and_still_drops_home(self) -> None:
        from immich_memories.analysis.familiar_places import PlaceHistory, PlaceObservation
        from immich_memories.generate_captions import apply_location_captions
        from immich_memories.processing.assembly_config import AssemblyClip

        # A public landmark abroad, and a synthetic home a long way from it.
        away = AssemblyClip(
            path=Path("/x/a.mp4"),
            duration=3.0,
            latitude=35.17,
            longitude=33.36,
            location_name="Nicosia, Cyprus",
        )
        at_home = AssemblyClip(
            path=Path("/x/b.mp4"),
            duration=3.0,
            latitude=48.86,
            longitude=2.35,
            location_name="Lyon, France",
        )
        history = PlaceHistory([PlaceObservation(48.86, 2.35, date(2024, 1, 1), "France")])

        captioned = apply_location_captions(
            [away, at_home], history, home=(48.86, 2.35), locale="fr"
        )

        assert captioned[0].caption_location_name == "Nicosia, Chypre"
        assert captioned[1].caption_location_name == ""

    def test_map_pins_carry_localised_names(self) -> None:
        from immich_memories.generate_privacy import extract_trip_pins
        from immich_memories.processing.assembly_config import AssemblyClip

        clips = [
            AssemblyClip(
                path=Path("/x/a.mp4"),
                duration=3.0,
                latitude=35.17,
                longitude=33.36,
                location_name="Nicosia, Cyprus",
            )
        ]

        _locations, names = extract_trip_pins(clips, locale="fr")

        assert names == ["Nicosia, Chypre"]

    def test_a_location_card_is_titled_in_the_film_s_language(self) -> None:
        from immich_memories.processing.assembly_config import TitleScreenSettings
        from immich_memories.processing.title_divider_planner import TitleDividerPlanner

        asked: list[str] = []

        class _Generator:
            def generate_location_card_screen(self, name, lat=None, lon=None):
                asked.append(name)
                return type("Screen", (), {"path": Path("card.mp4")})()

        planner = TitleDividerPlanner(
            _Generator(),  # type: ignore[arg-type]
            TitleScreenSettings(locale="fr"),
        )
        planner.make_location_card_clip("Nicosia, Cyprus", {})

        assert asked == ["Nicosia, Chypre"]


class TestTheNominatimRequest:
    """What leaves the host when geocoding is on, and what is kept of the answer."""

    def _fetch(self, monkeypatch: pytest.MonkeyPatch, raw: dict, url: str = ""):
        asked: dict = {}

        class _Answer:
            def __init__(self) -> None:
                self.raw = raw

        class _Geolocator:
            def __init__(self, **kwargs) -> None:
                asked["client"] = kwargs

            def reverse(self, query, **kwargs):
                asked["query"] = query
                asked.update(kwargs)
                return _Answer() if raw else None

        def _limiter(call, **kwargs):
            asked["limiter"] = kwargs
            return call

        # WHY: Nominatim is the outside host, and RateLimiter would hold the test for a
        # second per call. Both are replaced; the request and the parsing are ours.
        monkeypatch.setattr("geopy.geocoders.Nominatim", _Geolocator)
        monkeypatch.setattr("geopy.extra.rate_limiter.RateLimiter", _limiter)
        from immich_memories.analysis.place_geocoder import nominatim_fetch

        return nominatim_fetch("fr", url), asked

    def test_it_asks_once_a_second_at_district_zoom_in_the_films_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetch, asked = self._fetch(monkeypatch, {"address": {"suburb": "Wilrijk"}})
        fetch(51.17, 4.39)

        assert asked["query"] == "51.17, 4.39"
        assert (asked["zoom"], asked["language"]) == (14, "fr")
        assert asked["limiter"]["min_delay_seconds"] >= 1
        assert asked["client"]["domain"] == "nominatim.openstreetmap.org"
        assert asked["client"]["user_agent"].startswith("immich-memories/")

    def test_a_self_hosted_nominatim_takes_the_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetch, asked = self._fetch(
            monkeypatch, {"address": {}}, url="http://nominatim.lan:8080/geo/"
        )

        assert asked["client"]["domain"] == "nominatim.lan:8080/geo"
        assert asked["client"]["scheme"] == "http"

    def test_only_the_administrative_names_are_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = {
            "address": {
                "road": "Boomsesteenweg",
                "postcode": "2610",
                "suburb": "Wilrijk",
                "city": "Antwerpen",
                "country": "Belgique",
            }
        }
        fetch, _asked = self._fetch(monkeypatch, raw)

        assert fetch(51.17, 4.39) == {
            "suburb": "Wilrijk",
            "city": "Antwerpen",
            "country": "Belgique",
        }

    def test_a_coordinate_nobody_can_name_answers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetch, _asked = self._fetch(monkeypatch, {})

        assert fetch(0.0, -30.0) is None


class TestGeocodingReachesTheCut:
    """`prepare_location_captions` is where the switch turns into better names."""

    def _params(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, geocoding: bool):
        from immich_memories.config import Config
        from immich_memories.generate import GenerationParams

        monkeypatch.setenv("HOME", str(tmp_path))
        config = Config()
        config.network.geocoding = geocoding
        config.database.url = f"sqlite:///{tmp_path / 'store.db'}"
        config.title_screens.locale = "fr"
        return GenerationParams(
            clips=[], output_path=tmp_path / "out.mp4", config=config, add_place_overlay=True
        )

    def _clip(self):
        from immich_memories.processing.assembly_config import AssemblyClip

        # Immich names Wilrijk after the nearest GeoNames point: its neighbour Hoboken.
        return AssemblyClip(
            path=Path("/x/a.mp4"),
            duration=3.0,
            latitude=51.1682,
            longitude=4.3931,
            location_name="Hoboken, Belgium",
        )

    def _named(self, params, clip):
        from immich_memories.generate_captions import (
            district_place_names,
            prepare_location_captions,
        )

        return prepare_location_captions(params, district_place_names(params, [clip]))[0]

    def test_off_asks_nobody_and_keeps_immichs_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(*_args: object, **_kwargs: object):
            raise AssertionError("the default run must not build a geocoder")

        # WHY: Nominatim is the outside host; a request builder that raises proves the
        # default path never reaches it.
        monkeypatch.setattr("immich_memories.analysis.place_geocoder.nominatim_fetch", refuse)

        clip = self._named(self._params(tmp_path, monkeypatch, False), self._clip())

        assert clip.location_name == "Hoboken, Belgium"
        assert clip.caption_location_name == "Hoboken, Belgique"

    def test_on_names_the_district_in_the_films_language(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built: list[tuple[str, str]] = []

        def fetch(language: str, url: str = ""):
            built.append((language, url))
            return lambda *_p: {"suburb": "Wilrijk", "city": "Antwerpen", "country": "Belgique"}

        # WHY: same host, answering this time.
        monkeypatch.setattr("immich_memories.analysis.place_geocoder.nominatim_fetch", fetch)

        clip = self._named(self._params(tmp_path, monkeypatch, True), self._clip())

        assert clip.location_name == "Wilrijk, Belgium"
        assert clip.caption_location_name == "Wilrijk, Belgique"
        assert built == [("fr", "")]


def test_a_chinese_or_japanese_caption_place_takes_its_own_comma():
    from immich_memories.i18n_places import place_label

    assert place_label("Tokyo", "Japan", "ja") == "Tokyo、日本"
    assert place_label("Hangzhou", "China", "zh-Hans") == "Hangzhou，中国"
    assert place_label("Seoul", "South Korea", "ko") == "Seoul, 대한민국"
