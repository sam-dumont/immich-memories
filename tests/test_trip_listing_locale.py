"""The trip listing (`generate --memory-type trip` discovery table) names a trip the
same way its film title does: one scale, every part in the film's language (#2152).
"""

from __future__ import annotations

from datetime import date

from immich_memories.analysis.trip_detection import DetectedTrip
from immich_memories.cli._trip_display import format_trips_table


def _trip(place: str, kind: str) -> DetectedTrip:
    return DetectedTrip(
        start_date=date(2024, 6, 20),
        end_date=date(2024, 6, 26),
        location_name=place,
        location_kind=kind,
        asset_count=42,
        centroid_lat=0.0,
        centroid_lon=0.0,
    )


def test_a_region_and_country_show_in_one_language():
    # Immich/GeoNames give a region in the local script and the country in English;
    # the rest of a French film is French, so the listing must match.
    table = format_trips_table([_trip("Crete, Greece", "island")], locale="fr")

    assert table is not None
    assert table.columns[1]._cells == ["Crète, Grèce"]


def test_two_regions_localise_both_sides_of_the_join():
    table = format_trips_table([_trip("Tuscany and Lombardy, Italy", "regions")], locale="fr")

    assert table is not None
    assert table.columns[1]._cells == ["Toscane et Lombardie, Italie"]


def test_a_multi_country_trip_localises_every_country():
    table = format_trips_table([_trip("Belgium → France", "countries")], locale="fr")

    assert table is not None
    assert table.columns[1]._cells == ["Belgique → France"]


def test_english_locale_leaves_the_raw_name_as_is():
    table = format_trips_table([_trip("Crete, Greece", "island")], locale="en")

    assert table is not None
    assert table.columns[1]._cells == ["Crete, Greece"]


def test_default_locale_is_english():
    table = format_trips_table([_trip("Crete, Greece", "island")])

    assert table is not None
    assert table.columns[1]._cells == ["Crete, Greece"]
