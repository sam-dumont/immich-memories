"""Place names in the film's language.

Immich geocodes with GeoNames and stores English, so every city, region and
country reaching a clip overlay, a map pin, a location card or a trip title is
English whatever the film's locale is. A French film read "10 JOURS A CYPRUS"
and captioned its clips "Nicosia, Cyprus".

Country names come from CLDR through babel, offline, so this works with
`network.geocoding` off. City and region names have no offline translation:
they stay as Immich stored them unless a geocoder is allowed, and that is what
the switch buys.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

from babel import Locale, UnknownLocaleError

# Immich stores English place names, so that is the language a name is read in.
SOURCE_LOCALE = "en"

# French picks a country's preposition from its article: "en Italie" (la, or a
# vowel), "au Portugal" (le), "aux États-Unis" (les), "à Chypre" (none). The
# article follows the name's ending, so only the countries that break that rule
# are listed, by CLDR code.
_FR_PLURAL = frozenset(
    {"AE", "BS", "CK", "FK", "FO", "KM", "KY", "MH", "MV", "NL", "PH", "SB", "SC", "TC", "US"}
)
_FR_NO_ARTICLE = frozenset(
    {"BH", "CU", "CY", "DJ", "HK", "MC", "MG", "MO", "MT", "MU", "OM", "SG", "SM", "ST", "TW"}
)
_FR_MASCULINE_IN_E = frozenset({"BZ", "KH", "MX", "MZ", "ZW"})
# A mute h elides like a vowel: "en Haïti".
_FR_MUTE_H = frozenset({"HT"})


@lru_cache(maxsize=1)
def _codes_by_english_name() -> dict[str, str]:
    """CLDR territory name -> code, folded for lookup ("Cyprus" -> "CY")."""
    codes = {name.casefold(): code for code, name in Locale(SOURCE_LOCALE).territories.items()}
    # GeoNames/Immich uses these official names where CLDR uses shorter display names.
    codes.update(
        {
            "united states of america": "US",
            "state of palestine": "PS",
            "czech republic": "CZ",
            "russian federation": "RU",
        }
    )
    # GeoNames' countryInfo.txt short names (immich-app/immich#30199 rewrites
    # asset_exif.country to these on Immich 3.3) differ from CLDR's for every
    # entry below. Two defunct codes (CS, AN) have no CLDR entry of their own,
    # so they alias to their nearest living successor instead.
    codes.update(
        {
            "antigua and barbuda": "AG",
            "aland islands": "AX",
            "bosnia and herzegovina": "BA",
            "saint barthelemy": "BL",
            "bonaire, saint eustatius and saba": "BQ",
            "cocos islands": "CC",
            "democratic republic of the congo": "CD",
            "republic of the congo": "CG",
            "ivory coast": "CI",
            "cabo verde": "CV",
            "curacao": "CW",
            "south georgia and the south sandwich islands": "GS",
            "hong kong": "HK",
            "heard island and mcdonald islands": "HM",
            "saint kitts and nevis": "KN",
            "saint lucia": "LC",
            "saint martin": "MF",
            "myanmar": "MM",
            "macao": "MO",
            "the netherlands": "NL",
            "saint pierre and miquelon": "PM",
            "pitcairn": "PN",
            "palestinian territory": "PS",
            "reunion": "RE",
            "saint helena": "SH",
            "svalbard and jan mayen": "SJ",
            "sao tome and principe": "ST",
            "turks and caicos islands": "TC",
            "timor leste": "TL",
            "turkey": "TR",
            "trinidad and tobago": "TT",
            "united states minor outlying islands": "UM",
            "vatican": "VA",
            "saint vincent and the grenadines": "VC",
            "wallis and futuna": "WF",
            "serbia and montenegro": "RS",
            "netherlands antilles": "CW",
        }
    )
    return codes


def country_code(english_name: str) -> str | None:
    """The territory identity shared by Immich's names and translated display names."""
    return _codes_by_english_name().get(english_name.strip().casefold())


@lru_cache(maxsize=32)
def _territories(locale: str) -> dict[str, str]:
    try:
        return dict(Locale.parse(locale.replace("-", "_")).territories)
    except (UnknownLocaleError, ValueError, TypeError):
        return {}


def localise_country(english_name: str, locale: str) -> str:
    """The country's name in `locale`, or the name as given.

    A name CLDR does not know, a locale it does not know, and English itself
    all come back unchanged, so this is safe to call on anything.
    """
    if not english_name:
        return english_name
    code = _codes_by_english_name().get(english_name.strip().casefold())
    if code is None:
        return english_name
    return _territories(locale).get(code, english_name)


def french_preposition(english_place: str) -> str:
    """The preposition a French title puts before this place: "à", "en", "au" or "aux".

    A "City, Country" label and a place CLDR does not know as a country take
    "à", which is right for a city and the least wrong guess for anything else.
    """
    code = _codes_by_english_name().get(english_place.strip().casefold())
    if code is None or code in _FR_NO_ARTICLE:
        return "à"
    if code in _FR_PLURAL:
        return "aux"
    french = _territories("fr").get(code, "")
    bare = unicodedata.normalize("NFD", french).casefold()
    if code in _FR_MUTE_H or bare[:1] in "aeiou":
        return "en"
    if bare.endswith("e") and code not in _FR_MASCULINE_IN_E:
        return "en"
    return "au"


# Chinese and Japanese write a full-width comma with no space after it; ", " is
# a Latin comma set in the middle of their text.
_COMMAS = {"ja": "、", "zh-Hans": "，"}


def comma(locale: str) -> str:
    """The comma, with its space, that separates two parts of a label in this language."""
    return _COMMAS.get(locale, ", ")


def localise_place(name: str | None, locale: str) -> str | None:
    """Translate a "Place, Country" label: the country, and the place when it is known.

    A city keeps whatever the source called it: CLDR has no city names, and
    inventing one would be worse than showing the real one. Islands and
    regions a trip is named after have a short offline table (`place_names`).
    """
    from immich_memories.place_names import localise_place_part

    if not name:
        return name
    head, separator, tail = name.rpartition(", ")
    if not separator:
        return localise_country(name, locale)
    return f"{localise_place_part(head, locale)}{comma(locale)}{localise_country(tail, locale)}"


def localise_trip_place(english: str, kind: str, locale: str) -> str:
    """A trip's name, in the film's language, at the scale trip naming chose.

    `english` and `kind` are what `trip_place`/`_derive_location_name` produce: a
    "Place, Country" label (or "A and B, Country", or a bare country) for every
    `kind` except "countries", which is "A → B" and has no country tail to split
    off. Every surface that names a trip -- the film's own title, the trip
    listing, the web picker -- must call this on the same two values, so a
    French film never reads a region's name in French next to its country in
    English, or a bare English label where everything else around it is French.
    """
    if kind == "countries":
        return " → ".join(localise_country(c, locale) for c in english.split(" → "))
    return localise_place(english, locale) or english


def place_label(city: str | None, country: str | None, locale: str) -> str | None:
    """The label a viewer reads for one place, or None when there is no place."""
    localised = localise_country(country, locale) if country else None
    if city and localised:
        return f"{city}{comma(locale)}{localised}"
    return localised or city or None


def is_country(english_name: str) -> bool:
    """Whether CLDR knows this English name as a country."""
    return english_name.strip().casefold() in _codes_by_english_name()
