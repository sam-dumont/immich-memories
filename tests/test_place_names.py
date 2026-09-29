"""Every name a viewer reads comes from one resolver: the district, when geocoding found one."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from immich_memories.analysis.place_geocoder import PlaceGeocoder
from immich_memories.analysis.place_names import PlaceNames, shown_city
from immich_memories.api.models import ExifInfo
from immich_memories.db import open_store
from tests.conftest import make_asset

# Immich names this point after the nearest GeoNames town; OpenStreetMap knows the district.
POINT = (51.1682, 4.3931)
NOMINATIM = {"suburb": "Wilrijk", "city": "Antwerpen", "country": "Belgique"}


def _asset(asset_id: str = "a1", *, taken: datetime | None = None):
    asset = make_asset(asset_id, file_created_at=taken)
    asset.exif_info = ExifInfo(
        latitude=POINT[0], longitude=POINT[1], city="Hoboken", state="Antwerp", country="Belgium"
    )
    return asset


def _names(answer=NOMINATIM) -> PlaceNames:
    def fetch(_latitude, _longitude):
        if isinstance(answer, Exception):
            raise answer
        return answer

    # WHY: the fake fetch stands in for Nominatim, the one outside host.
    return PlaceNames(PlaceGeocoder(open_store(), "fr", fetch))


def test_a_named_picture_shows_the_district_and_keeps_immichs_city_for_matching():
    asset = _asset()

    _names().name([asset])

    assert shown_city(asset.exif_info) == "Wilrijk"
    assert asset.exif_info.city == "Hoboken"


@pytest.mark.parametrize(
    "names",
    [lambda: PlaceNames(None), lambda: _names(ConnectionError("down"))],
    ids=["off", "failing"],
)
def test_without_an_answer_the_picture_keeps_immichs_name(names):
    asset = _asset()

    names().name([asset])

    assert shown_city(asset.exif_info) == "Hoboken"


def test_the_clip_a_location_card_and_a_caption_read_names_the_district():
    from immich_memories.generate_privacy import clip_location_name

    asset = _asset()
    _names().name([asset])

    assert clip_location_name(asset.exif_info) == "Wilrijk, Belgium"


def test_the_report_keeps_the_district_as_private_as_the_city():
    from immich_memories.tracking import report_context

    asset = _asset()
    _names().name([asset])

    assert {"Wilrijk", "Hoboken"} <= set(report_context._asset_labels(asset))


def test_a_rules_story_is_titled_after_the_district():
    from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
    from immich_memories.config_models_editorial import EditorialPeopleConfig

    assets, moments, annotations = {}, {}, {}
    names = _names()
    for day in (1, 2):
        ids = []
        for n in range(6):
            taken = datetime(2022, 5, day, 10) + timedelta(minutes=n)
            asset = _asset(f"d{day}-{n}", taken=taken)
            names.name([asset])
            assets[asset.id] = asset
            annotations[asset.id] = f"{taken.isoformat()} | posing | alone"
            ids.append(asset.id)
        moments[f"M{day:02}"] = tuple(ids)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps=dict.fromkeys(assets, POINT),
        annotations=annotations,
        audience_annotations={},
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=0.0, homebase_longitude=0.0),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(product="monthly_highlights"),
        case=SimpleNamespace(product="monthly_highlights", people=()),
        people=None,
    )

    def enrich(episodes):
        return {
            e.key: {"day": date(2022, 5, int(e.moments[0][1:])).isoformat(), "pictures": 6}
            for e in episodes
        }

    story = RuleStructureReader(source).read_story(
        None, evidence=[], enrich=enrich, record=lambda _record: None
    )
    titles = " ".join(e.title for e in story.episodes)

    assert "Wilrijk" in titles
    assert "Hoboken" not in titles


class CountingNominatim:
    """Answers like Nominatim and counts the questions that would have left the host."""

    def __init__(self, answers):
        self.answers = answers
        self.asked: list[tuple[float, float]] = []

    def __call__(self, latitude, longitude):
        self.asked.append((latitude, longitude))
        return self.answers.get((latitude, longitude))


def _at(asset_id: str, latitude: float, longitude: float):
    asset = make_asset(asset_id)
    asset.exif_info = ExifInfo(latitude=latitude, longitude=longitude, city="Hoboken")
    return asset


def test_a_second_run_asks_only_about_new_places_and_never_twice_about_nothing():
    nominatim = CountingNominatim({(51.17, 4.39): NOMINATIM})
    # WHY: the counting fetch stands in for Nominatim, the one outside host.
    first = PlaceNames(PlaceGeocoder(open_store(), "fr", nominatim))
    first.name([_at("a", 51.1682, 4.3931), _at("b", 51.1712, 4.3911), _at("c", 51.20, 3.22)])
    assert len(nominatim.asked) == 2  # one question per ~1 km cell; the second cell had nothing

    later = PlaceNames(PlaceGeocoder(open_store(), "fr", nominatim))
    later.name([_at("d", 51.1682, 4.3931), _at("e", 51.20, 3.22), _at("f", 50.50, 4.00)])

    assert len(nominatim.asked) == 3  # only the new cell
    assert later.district_at(51.1682, 4.3931) == "Wilrijk"  # a second surface, no new question
    assert len(nominatim.asked) == 3
