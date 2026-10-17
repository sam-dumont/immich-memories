"""A place name OpenStreetMap writes in several scripts reaches the film in one (#2637).

Morocco's `name` tags hold Latin, Tifinagh and Arabic at once. Nominatim answers with
that plain tag when a place has no name in the asked language, so a Spanish film
captioned "OUAHAT SIDI BRAHIM واحة سيدي ابراهيم, MAR…". The owner's ruling holds: no
English fallback, a place without a name in the film's language keeps its native name,
but one name, in one script.

The addresses below are the reporter's `geocoded_places` rows (Marrakesh, public OSM
names): exactly what `nominatim_fetch` keeps of a real answer and the store holds.
"""

from __future__ import annotations

import pytest

from immich_memories.analysis.places.geocoder import PlaceGeocoder
from immich_memories.analysis.places.names import PlaceNames, shown_city
from immich_memories.api.models import ExifInfo
from immich_memories.db import open_store
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.place_names import locality_name, one_script_name
from tests.conftest import make_asset

OUAHAT = "Ouahat Sidi Brahim واحة سيدي ابراهيم"
MEDINA = "Medina ⵎⴷⵉⵏⴰ المدينة"  # Latin, Tifinagh, Arabic
GUELIZ = "Arrondissement de Gueliz مقاطعة كليز"
MENARA = "Arrondissement de Ménara مقاطعة المنارة"

# Rounded public point near Marrakesh, and the reporter's stored Spanish answer.
MARRAKESH = (31.66, -7.99)
ANSWER_ES = {"village": OUAHAT, "suburb": MEDINA, "country": "Marruecos", "country_code": "ma"}

# French first (the owner's own render language), then every other film language.
_LOCALES = ["fr", *[loc for loc in SUPPORTED_LOCALES if loc != "fr"]]


@pytest.mark.parametrize("locale", _LOCALES)
@pytest.mark.parametrize(
    "stored,expected",
    [(OUAHAT, "Ouahat Sidi Brahim"), (MEDINA, "Medina"), (GUELIZ, "Arrondissement de Gueliz")],
)
def test_no_film_language_shows_more_than_one_script(locale, stored, expected):
    # No film language is written in Arabic or Tifinagh, so every one of them keeps the
    # Latin run: the Latin languages because it is theirs, the others because it is first.
    assert one_script_name(stored, locale) == expected


@pytest.mark.parametrize(
    "language,stored,expected",
    [
        ("es", OUAHAT, "Ouahat Sidi Brahim"),
        ("en", MENARA, "Arrondissement de Ménara"),
        ("ar", OUAHAT, "واحة سيدي ابراهيم"),
        ("ar", MEDINA, "المدينة"),
        ("ar", GUELIZ, "مقاطعة كليز"),
        # Greek has no run here: the native name, its first script only, never all three.
        ("el", MEDINA, "Medina"),
        # A Greek film keeps the Greek run of a bilingual name.
        ("el", "Chania Χανιά", "Χανιά"),
        ("fr", "Agadir (أكادير)", "Agadir"),
        ("fr", "Tanger - طنجة", "Tanger"),
    ],
)
def test_the_run_in_the_film_languages_script_wins(language, stored, expected):
    assert one_script_name(stored, language) == expected


@pytest.mark.parametrize(
    "name", ["Παλαιό Γεράνι", "Saint-Jean-Cap-Ferrat", "東京都", "Petropavlovsk-Kamtchatski"]
)
def test_a_name_in_one_script_is_left_alone(name):
    # Greek in a French film stays Greek: no fallback, no translation.
    assert one_script_name(name, "fr") == name


def test_a_name_with_no_word_in_it_names_nothing():
    assert one_script_name(" - ", "fr") is None


def test_the_admin_word_left_in_the_latin_run_is_dropped():
    assert locality_name(one_script_name(GUELIZ, "fr")) == "Gueliz"


def _picture_in_marrakesh(city: str | None = "Marrakesh"):
    asset = make_asset("ma1")
    asset.exif_info = ExifInfo(
        latitude=MARRAKESH[0], longitude=MARRAKESH[1], city=city, country="Morocco"
    )
    return asset


@pytest.mark.parametrize(
    "language,expected", [("fr", "Ouahat Sidi Brahim"), ("es", "Ouahat Sidi Brahim")]
)
def test_the_picture_is_named_in_one_script(language, expected):
    asset = _picture_in_marrakesh()
    # WHY: the fake fetch stands in for Nominatim, the one outside host.
    geocoder = PlaceGeocoder(open_store(), language, lambda *_: dict(ANSWER_ES))

    PlaceNames(geocoder).name([asset])

    assert shown_city(asset.exif_info) == expected


def test_an_arabic_film_keeps_the_arabic_name():
    asset = _picture_in_marrakesh()
    # WHY: the fake fetch stands in for Nominatim, the one outside host.
    PlaceNames(PlaceGeocoder(open_store(), "ar", lambda *_: dict(ANSWER_ES))).name([asset])

    assert shown_city(asset.exif_info) == "واحة سيدي ابراهيم"


def test_a_name_with_nothing_usable_keeps_immichs_own():
    asset = _picture_in_marrakesh()
    answer = {"village": " - ", "country_code": "ma"}
    # WHY: the fake fetch stands in for Nominatim, the one outside host.
    PlaceNames(PlaceGeocoder(open_store(), "es", lambda *_: answer)).name([asset])

    assert shown_city(asset.exif_info) == "Marrakesh"
