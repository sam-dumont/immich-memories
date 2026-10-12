"""The fake Immich answers what a real Immich answers, for every read the app makes of the library.

Runs only in the real-Immich pass (`make test-features-real-immich`): a fake Immich serving the
fixture library is asked the same questions as the real one seeded with the same files, and
every answer is compared after the ids are mapped back to the fixture's. A difference fails with
the field, the fake's answer and the real one; the fix is in the fake (`tests/e2e/fake_immich.py`,
`tests/e2e/fake_library.py`) unless the real answer shows a product bug.

The three behaviours the fake once got wrong (tag search answering with the whole library, dates
compared as text, no reverse geocoding) each have a check here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx
import pytest

from tests.e2e.fake_immich import (
    ALBUM_ID,
    ALBUMS,
    COMPANION_ASSETS,
    PARTNER_ASSETS,
    PARTNER_PEOPLE,
    TIMELINE_ASSETS,
    FakeImmichServer,
)
from tests.e2e.fake_library import ALL_PICTURES, CAST, HOME, PARTNER_PICTURES
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import GARDEN_DAY

pytestmark = [pytest.mark.integration, pytest.mark.real_immich_only]

_PAGE = {"page": 1, "size": 1000, "withExif": True, "withPeople": True}

# The fixture names its places by hand (Brussels, Tervuren, Semnoz); a real Immich names each
# after the nearest GeoNames town (Ixelles, Watermael-Boitsfort, Gruffy). The real-Commons
# fixture library (#2423) brings places named the way Immich names them; until then the place
# names are compared on their own and expected to differ.
_PLACE_NAMES_DIFFER = pytest.mark.xfail(
    strict=True,
    reason="the fixture's hand-picked place names are not Immich's GeoNames names (#2423)",
)
# The fake answers a person's timeline with the whole library's months; a real Immich counts
# that person's pictures only. Making the fake honest leaves the web "Rescan now" with nobody
# over its 25-picture floor on this library, which the people-page e2e test relies on: that
# needs a ruling first.
_PERSON_TIMELINE_DIFFERS = pytest.mark.xfail(
    strict=True,
    reason="the fake gives each person the whole library's timeline until the web scan's floor scales with the library (#2424)",
)


class _Pair:
    """The same request to the fake and to the real server, answers mapped to fixture ids."""

    def __init__(self, fake: FakeImmichServer, real: LibraryServer) -> None:
        self.fake, self.real = fake, real
        self.fixture_of = {server: fixture for fixture, server in real.asset_ids.items()}
        self._fake = httpx.Client(base_url=f"{fake.base_url}/api", timeout=60)
        self._real = httpx.Client(base_url=f"{real.base_url}/api", timeout=60)

    def ask(
        self, method: str, path: str, *, partner: bool = False, real_path: str | None = None, **kw
    ) -> tuple[Any, Any]:
        """(fake answer, real answer); `real_path` names the real server's ids where they differ."""
        fake_key = self.fake.partner_api_key if partner else self.fake.api_key
        real_key = self.real.partner_api_key if partner else self.real.api_key
        real_kw = kw.pop("real", kw)
        fake = self._fake.request(method, path, headers={"x-api-key": fake_key}, **kw)
        real = self._real.request(
            method, real_path or path, headers={"x-api-key": real_key}, **real_kw
        )
        assert fake.status_code < 400, (path, fake.status_code, fake.text[:300])
        assert real.status_code < 400, (path, real.status_code, real.text[:300])
        return fake.json(), real.json()

    def close(self) -> None:
        self._fake.close()
        self._real.close()


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory, immich: LibraryServer) -> Iterator[_Pair]:
    # The fake, started here on purpose: the session's `fake_immich` refuses a real-Immich run.
    fake = FakeImmichServer.start(tmp_path_factory.mktemp("fake-for-parity"))
    with fake.answering_as(immich.major):
        both = _Pair(fake, immich)
        yield both
        both.close()
    fake.close()
    assert fake.refused == [], fake.refused


def _instant(stamp: str | None) -> str | None:
    if not stamp:
        return None
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).isoformat()


def _seconds(duration: Any) -> float | None:
    """v3 milliseconds and v2 "H:MM:SS.ffffff" both as seconds; a photo has none."""
    if duration is None:
        return None
    if isinstance(duration, int | float):
        return round(duration / 1000, 1) or None
    hours, minutes, seconds = str(duration).split(":")
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 1) or None


def _facts(asset: dict[str, Any], pair: _Pair, *, real: bool) -> dict[str, Any]:
    """What the app reads of one asset, ids turned back into the fixture's."""
    exif = asset.get("exifInfo") or {}
    live = asset.get("livePhotoVideoId")
    return {
        "type": asset.get("type"),
        "originalFileName": asset.get("originalFileName"),
        "fileCreatedAt": _instant(asset.get("fileCreatedAt")),
        "localDateTime": _instant(asset.get("localDateTime")),
        "isFavorite": asset.get("isFavorite"),
        "isEdited": asset.get("isEdited"),
        "visibility": asset.get("visibility", "timeline"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "duration": _seconds(asset.get("duration")),
        "make": exif.get("make"),
        "model": exif.get("model"),
        "country": exif.get("country"),
        "people": sorted(person["name"] for person in asset.get("people") or ()),
        "livePhotoVideoId": pair.fixture_of.get(live, live) if real else live,
    }


def _differences(label: str, fake: dict[str, Any], real: dict[str, Any]) -> list[str]:
    return [
        f"{label} {key}: fake={fake[key]!r} real={real.get(key)!r}"
        for key in fake
        if fake[key] != real.get(key)
    ]


@pytest.mark.parametrize(
    ("account", "assets"),
    [("primary", (*TIMELINE_ASSETS, *COMPANION_ASSETS)), ("partner", PARTNER_ASSETS)],
)
def test_every_asset_reads_the_same(pair: _Pair, account: str, assets: tuple) -> None:
    found: list[str] = []
    for fixture_id, fake, real in _each_asset(pair, account == "partner", assets):
        found += _differences(
            fixture_id, _facts(fake, pair, real=False), _facts(real, pair, real=True)
        )
    assert found == [], "\n".join(found)


@_PLACE_NAMES_DIFFER
def test_every_asset_is_named_after_the_same_place(pair: _Pair) -> None:
    found = [
        f"{fixture_id}: fake={city(fake)!r} real={city(real)!r}"
        for fixture_id, fake, real in _each_asset(pair, False, TIMELINE_ASSETS)
        if city(fake) != city(real)
    ]
    assert found == [], "\n".join(found)


def city(asset: dict[str, Any]) -> str | None:
    return (asset.get("exifInfo") or {}).get("city")


def _each_asset(
    pair: _Pair, partner: bool, assets: tuple
) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(fixture id, the fake's answer, the real one's) for each asset, read by id."""
    for asset in assets:
        fixture_id = asset["id"]
        fake, real = pair.ask(
            "GET",
            f"/assets/{fixture_id}",
            partner=partner,
            real_path=f"/assets/{pair.real.id_of(fixture_id)}",
        )
        yield fixture_id, fake, real


def _searches(pair: _Pair) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(label, the fake's payload, the real one's): the shapes the app sends."""
    month = (min(p.taken_at for p in ALL_PICTURES), max(p.taken_at for p in ALL_PICTURES))
    day_end = f"{GARDEN_DAY}T23:59:59.999Z"
    candles = next(p for p in ALL_PICTURES if p.scene == "birthday-candles" and p.shipped)
    cases: list[tuple[str, dict[str, Any]]] = [
        ("everything", {}),
        ("photos", {"type": "IMAGE"}),
        ("videos", {"type": "VIDEO"}),
        ("the month", {"takenAfter": month[0], "takenBefore": month[1]}),
        ("one day, Z", {"takenAfter": f"{GARDEN_DAY}T00:00:00.000Z", "takenBefore": day_end}),
        # The same instant spelled with an offset: Immich compares instants, not text.
        ("one day, +00:00", {"takenAfter": f"{GARDEN_DAY}T00:00:00+00:00"}),
        ("from an exact capture", {"takenAfter": candles.taken_at}),
        ("up to an exact capture", {"takenBefore": candles.taken_at.replace(".000Z", "+00:00")}),
        ("the lake album", {"albumIds": [ALBUM_ID]}),
        ("on the timeline", {"visibility": "timeline"}),
        ("hidden", {"visibility": "hidden"}),
    ]
    cases += [(f"person {name}", {"personIds": [f"person-{name.lower()}"]}) for name in CAST]
    cases.append(("two people", {"personIds": [f"person-{name.lower()}" for name in CAST[:2]]}))

    def real(payload: dict[str, Any]) -> dict[str, Any]:
        mapped = dict(payload)
        if "personIds" in payload:
            mapped["personIds"] = [pair.real.person_of(p) for p in payload["personIds"]]
        if "albumIds" in payload:
            mapped["albumIds"] = [pair.real.album_ids[a] for a in payload["albumIds"]]
        return mapped

    return [(label, payload, real(payload)) for label, payload in cases]


def _found(answer: dict[str, Any], pair: _Pair, *, real: bool) -> list[str]:
    items = answer["assets"]["items"]
    return sorted(pair.fixture_of.get(a["id"], a["id"]) if real else a["id"] for a in items)


def test_metadata_search_finds_the_same_pictures(pair: _Pair) -> None:
    found = []
    for label, fake_payload, real_payload in _searches(pair):
        fake, real = pair.ask(
            "POST",
            "/search/metadata",
            json=_PAGE | fake_payload,
            real={"json": _PAGE | real_payload},
        )
        fake_ids, real_ids = _found(fake, pair, real=False), _found(real, pair, real=True)
        if fake_ids != real_ids:
            only_fake = sorted(set(fake_ids) - set(real_ids))
            only_real = sorted(set(real_ids) - set(fake_ids))
            found.append(f"{label}: only the fake finds {only_fake}, only real finds {only_real}")
            continue
        # The app reads its pictures from these pages: each item as the asset read alone.
        real_by_id = {pair.fixture_of.get(a["id"], a["id"]): a for a in real["assets"]["items"]}
        for item in fake["assets"]["items"]:
            found += _differences(
                f"{label} {item['id']}",
                _facts(item, pair, real=False),
                _facts(real_by_id[item["id"]], pair, real=True),
            )
    assert found == [], "\n".join(found)


def test_search_statistics_count_the_same(pair: _Pair) -> None:
    found = []
    for label, fake_payload, real_payload in _searches(pair):
        fake, real = pair.ask(
            "POST", "/search/statistics", json=fake_payload, real={"json": real_payload}
        )
        if fake.get("total") != real.get("total"):
            found.append(f"{label}: fake={fake.get('total')} real={real.get('total')}")
    assert found == [], "\n".join(found)


def test_tag_search_finds_only_the_tagged_pictures(pair: _Pair) -> None:
    """The fake once answered a tag search with the whole library."""
    picture = next(p for p in ALL_PICTURES if p.shipped)
    value = "feature-parity/checked"
    fake_tag, real_tag = pair.ask("PUT", "/tags", json={"tags": [value]})
    fake_tag, real_tag = fake_tag[0]["id"], real_tag[0]["id"]
    pair.ask(
        "PUT",
        f"/tags/{fake_tag}/assets",
        real_path=f"/tags/{real_tag}/assets",
        json={"ids": [picture.asset_id]},
        real={"json": {"ids": [pair.real.id_of(picture.asset_id)]}},
    )

    fake, real = pair.ask(
        "POST",
        "/search/metadata",
        json=_PAGE | {"tagIds": [fake_tag]},
        real={"json": _PAGE | {"tagIds": [real_tag]}},
    )

    assert _found(fake, pair, real=False) == [picture.asset_id]
    assert _found(real, pair, real=True) == [picture.asset_id]


def test_timeline_buckets_count_the_same(pair: _Pair) -> None:
    fake, real = pair.ask("GET", "/timeline/buckets")
    assert fake == real


@_PERSON_TIMELINE_DIFFERS
def test_a_persons_timeline_buckets_count_the_same(pair: _Pair) -> None:
    found = []
    for name in CAST:
        person = f"person-{name.lower()}"
        fake, real = pair.ask(
            "GET",
            "/timeline/buckets",
            params={"personId": person},
            real={"params": {"personId": pair.real.person_of(person)}},
        )
        if fake != real:
            found.append(f"{name}: fake={fake} real={real}")
    assert found == [], "\n".join(found)


@_PLACE_NAMES_DIFFER
def test_reverse_geocoding_names_the_same_places(pair: _Pair) -> None:
    """The fake once named no place at all."""
    places = sorted(
        {p.place for p in (*ALL_PICTURES, *PARTNER_PICTURES) if p.place is not None} | {HOME},
        key=lambda place: (place.latitude, place.longitude),
    )
    found = []
    for place in places:
        params = {"lat": place.latitude, "lon": place.longitude}
        fake, real = pair.ask("GET", "/map/reverse-geocode", params=params)
        named = [(row.get("city"), row.get("country")) for row in fake]
        real_named = [(row.get("city"), row.get("country")) for row in real]
        if named != real_named:
            found.append(f"{place.latitude},{place.longitude}: fake={named} real={real_named}")
    assert found == [], "\n".join(found)


@pytest.mark.parametrize("account", ["primary", "partner"])
def test_people_and_their_counts_read_the_same(pair: _Pair, account: str) -> None:
    partner = account == "partner"
    fake, real = pair.ask("GET", "/people", partner=partner)

    def roster(answer: dict[str, Any]) -> list[tuple[str, str | None]]:
        return sorted((p["name"], p.get("birthDate")) for p in answer["people"])

    assert roster(fake) == roster(real)
    expected = [p[0] for p in PARTNER_PEOPLE] if partner else [f"person-{n.lower()}" for n in CAST]
    found = []
    for person in expected:
        fake_count, real_count = pair.ask(
            "GET",
            f"/people/{person}/statistics",
            partner=partner,
            real_path=f"/people/{pair.real.person_of(person)}/statistics",
        )
        if fake_count != real_count:
            found.append(f"{person}: fake={fake_count} real={real_count}")
    assert found == [], "\n".join(found)


def test_albums_read_the_same(pair: _Pair) -> None:
    fake, real = pair.ask("GET", "/albums")

    def shelf(answer: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return sorted(
            (
                a["albumName"],
                a["assetCount"],
                _instant(a.get("startDate")),
                _instant(a.get("endDate")),
            )
            for a in answer
        )

    assert shelf(fake) == shelf(real)
    assert [a["albumName"] for a in fake] == [ALBUMS[0]["albumName"]]
    inside = next(
        iter(sorted(a["id"] for a in TIMELINE_ASSETS if a["exifInfo"]["city"] == "Annecy"))
    )
    outside = next(a["id"] for a in TIMELINE_ASSETS if a["exifInfo"]["city"] != "Annecy")
    for fixture_id in (inside, outside):
        fake, real = pair.ask(
            "GET",
            "/albums",
            params={"assetId": fixture_id},
            real={"params": {"assetId": pair.real.id_of(fixture_id)}},
        )
        assert [a["albumName"] for a in fake] == [a["albumName"] for a in real], fixture_id
