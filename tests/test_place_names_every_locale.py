"""Island and region names reach every film language, not just the ones without prepositions."""

from __future__ import annotations

import pytest

from immich_memories.i18n_places import localise_place, localise_trip_place
from immich_memories.place_name_translations import TRANSLATIONS

_NEW_LOCALES = ["nl", "de", "es", "it", "pt-BR", "pt-PT", "pl", "sv"]
_REFERENCE = set(TRANSLATIONS["ru"])
# Names a language writes like English are left out and the fallback answers; the rest are stored.
_MIN_TRANSLATED = 20


@pytest.mark.parametrize("locale", _NEW_LOCALES)
def test_each_new_locale_covers_the_scope_of_the_existing_tables(locale):
    table = TRANSLATIONS[locale]

    assert set(table) <= _REFERENCE
    assert len(table) >= _MIN_TRANSLATED
    assert all(local and local != english for english, local in table.items())


def test_a_german_card_names_the_region_and_the_country_in_german():
    assert localise_place("Tuscany, Italy", "de") == "Toskana, Italien"
    assert localise_place("Crete, Greece", "de") == "Kreta, Griechenland"


def test_a_polish_card_names_the_region_and_the_country_in_polish():
    assert localise_place("Sicily, Italy", "pl") == "Sycylia, Włochy"
    assert localise_trip_place("Utah and Nevada, United States", "region", "pl") == (
        "Utah i Nevada, Stany Zjednoczone"
    )


def test_two_areas_join_with_the_language_s_own_word():
    assert localise_place("Corsica and Sardinia, Italy", "sv") == "Korsika och Sardinien, Italien"


def test_portuguese_variants_differ_where_the_spelling_does():
    assert localise_place("Saxony, Germany", "pt-PT") == "Saxónia, Alemanha"
    assert localise_place("Saxony, Germany", "pt-BR") == "Saxônia, Alemanha"


@pytest.mark.parametrize("locale", _NEW_LOCALES)
def test_an_unknown_place_keeps_the_name_it_came_with(locale):
    assert localise_place("Atlantis, Narnia", locale) == "Atlantis, Narnia"
    assert localise_place("Nowhere Valley", locale) == "Nowhere Valley"
