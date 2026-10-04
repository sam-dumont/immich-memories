"""Regenerate the raw Nominatim reverse-geocode fixtures in this directory.

Run with `python tests/fixtures/places/capture_nominatim_fixtures.py`.

#1954/#1947: the admin-wording stripper (`place_names.short_place_name`) must only
drop boilerplate it has actually seen in a real Nominatim answer, in the native
script and every supported film language, never a guessed translation. This
script is the one-off, owner-approved outside call that captures that real data;
the product itself never calls out at this frequency (`network.geocoding`, one
question per 1 km cell, cached forever).

Four public points, no personal data:
- a Greek point near Platanias, Chania (OSM boundary with no name in most film
  languages, which is what produced "Municipality of Platanias" in #1954)
- a second Greek point in Chania town itself, in the neighbouring municipality --
  real data for a trip that spans two municipalities, rather than guessing a
  second municipality's name
- a Belgian point in Laeken (bilingual fr/nl boundary, used by #1947's tests)
- an Italian point in an Apulian village (Comune di ... wording)

Each point is asked once per supported locale, with the exact `accept-language`
chain the product itself sends (`place_geocoder.accept_language_chain`: the film's
language, then its base language, e.g. "pt-BR,pt" -- never "en"), and once with no
`accept-language` at all (the native answer), at <=1 request/second with an
identifying User-Agent, matching `nominatim_fetch`'s own policy.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from immich_memories.analysis.place_geocoder import accept_language_chain
from immich_memories.i18n import SUPPORTED_LOCALES

OUTPUT_DIR = Path(__file__).parent
USER_AGENT = "immich-memories-fixture-capture/1.0 (+https://github.com/sam-dumont/immich-memories)"

POINTS = {
    "greece_platanias": (35.512, 23.879),
    "greece_chania": (35.5138, 24.0180),
    "belgium_laeken": (50.880, 4.355),
    "italy_apulia": (40.73, 17.58),
}


def _fetch(lat: float, lon: float, accept_language: str | None) -> dict:
    params = {
        "format": "jsonv2",
        "zoom": "16",
        "addressdetails": "1",
        "namedetails": "1",
        "lat": str(lat),
        "lon": str(lon),
    }
    if accept_language is not None:
        params["accept-language"] = accept_language
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return json.load(response)


def main() -> None:
    for place, (lat, lon) in POINTS.items():
        for locale in [*SUPPORTED_LOCALES, "native"]:
            accept_language = None if locale == "native" else accept_language_chain(locale)
            answer = _fetch(lat, lon, accept_language)
            path = OUTPUT_DIR / f"{place}_{locale}.json"
            path.write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n")
            print(f"wrote {path.name}")
            time.sleep(1)


if __name__ == "__main__":
    main()
