"""A picture's day, month and year are the ones its own clock showed (#2355).

Immich stores the instant (``fileCreatedAt``, UTC) and the clock the phone showed
(``localDateTime``). Its timeline files a picture under the latter, and so does every film:
a New Year's Eve party at 20:30 eight hours behind UTC is in the old year, however late it was in
UTC, and a 07:00 breakfast on 1 January ten hours ahead is in the new one.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from immich_memories.api.models import Asset, AssetType, ExifInfo
from immich_memories.timeperiod import DateRange, calendar_year

BEHIND_8 = timedelta(hours=-8)
AHEAD_10 = timedelta(hours=10)


def picture(
    key: str,
    local: datetime,
    offset: timedelta = timedelta(0),
    *,
    favourite: bool = False,
    local_clock: bool = True,
    where: tuple[float, float] | None = None,
) -> Asset:
    """A still taken at `local` on a clock `offset` from UTC, as Immich reports it.

    Immich writes the local clock with a ``Z`` it does not mean: the wall-clock digits,
    labelled UTC. ``local_clock=False`` is a server that sent no local clock at all.
    """
    instant = (local - offset).replace(tzinfo=UTC)
    return Asset(
        id=key,
        type=AssetType.IMAGE,
        fileCreatedAt=instant,
        fileModifiedAt=instant,
        updatedAt=instant,
        localDateTime=local.replace(tzinfo=UTC) if local_clock else None,
        isFavorite=favourite,
        originalFileName=f"IMG_{key}.HEIC",
        exifInfo=ExifInfo(
            make="Apple",
            model="iPhone 15 Pro",
            latitude=where[0] if where else None,
            longitude=where[1] if where else None,
        ),
    )


def _distinct_preview(key):
    import hashlib
    import io

    import numpy as np
    from PIL import Image

    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4])
    pixels = np.random.default_rng(seed).integers(30, 220, (128, 128, 3), dtype=np.uint8)
    out = io.BytesIO()
    Image.fromarray(pixels).save(out, format="JPEG")
    return out.getvalue()


def cut(
    tmp_path,
    product: str,
    windows: tuple[DateRange, ...],
    sources,
    *,
    context_only=(),
    client=None,
    **context,
):
    """The Basic cut of `sources` for `product`, and its private plan record.

    `context_only` are pictures the window holds that the film's own filter did not choose:
    the unfiltered context read a person film keeps beside its strict pool.
    """
    from immich_memories.analysis.runtime.composition import (
        EditorialRunContext,
        build_editorial_planner,
    )
    from immich_memories.analysis.runtime.ports import EditorialRuntimePorts
    from immich_memories.analysis.runtime.smart_pipeline import SmartPipeline
    from immich_memories.analysis.sources.pool import EditorialSourcePool
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.config.loader import Config

    config = Config(
        cache={"directory": str(tmp_path / "cache")},
        analysis={"min_source_short_side": 0},
    )
    config.editorial.preparation.tier = "metadata_only"

    def forbidden(*args, **kwargs):
        raise AssertionError("a Basic cut constructed an inference transport")

    planner = build_editorial_planner(
        source_pool=EditorialSourcePool(tuple(sources), tuple(context_only)),
        client=object() if client is None else client,
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "thumbnails"),
        context=EditorialRunContext(
            "local-time", "fixture", product, windows, 60, tmp_path / "artifacts", **context
        ),
        ports=EditorialRuntimePorts(
            load_people=lambda: {},
            fetch_preview=lambda _client, key: _distinct_preview(key),
            episode_requester_factory=forbidden,
        ),
    )
    _, result = SmartPipeline(planner=planner).run_editorial_source(list(sources))
    plan = json.loads((planner.last_attempt_directory / "plan.private.json").read_text())
    return {clip.asset.id for clip in result.selected_clips}, plan


@pytest.mark.feature("selection.local-time-dates")
def test_a_year_film_holds_new_years_eve_on_its_own_clock(tmp_path):
    year = [
        picture(f"day-{n:02}", datetime(2024, 1 + n % 12, 10, 12) + timedelta(days=n))
        for n in range(24)
    ]
    party = picture("eve-party", datetime(2024, 12, 31, 20, 30), BEHIND_8, favourite=True)
    breakfast = picture("new-year-breakfast", datetime(2025, 1, 1, 7), AHEAD_10, favourite=True)

    chosen, plan = cut(
        tmp_path, "year_in_review", (calendar_year(2024),), [*year, party, breakfast]
    )

    assert "eve-party" in chosen
    assert "new-year-breakfast" not in chosen
    assert _story_day_of("eve-party", plan) == "2024-12-31"


def _story_day_of(asset_id: str, plan) -> str:
    """The day the plan files the story carrying `asset_id` under."""
    moment = next(c["depicted_moment"] for c in plan["carriers"] if c["asset_id"] == asset_id)
    alias = moment.split(":")[0]
    return next(
        e["day"]
        for e in plan["story"]["episodes"]
        if f"{alias}:cg" in e["chosen"] or moment in e["chosen"]
    )


@pytest.mark.feature("on-this-day.new-year")
def test_on_this_day_new_year_gives_each_occurrence_its_own_voice(tmp_path):
    """#2357 and #2355: 1 January's windows run 31 Dec to 2 Jan, across a year boundary."""
    from immich_memories.memory_types.date_builders import build_on_this_day

    windows = tuple(build_on_this_day(date(2026, 1, 1), 3))
    sources = []
    for year in (2022, 2023, 2024):
        # New Year's Eve eight hours behind UTC: already 1 January in UTC.
        sources.append(
            picture(f"eve-{year}", datetime(year, 12, 31, 20, 30), BEHIND_8, favourite=True)
        )
        sources.append(picture(f"day-{year + 1}", datetime(year + 1, 1, 1, 11), favourite=True))

    chosen, plan = cut(tmp_path, "on_this_day", windows, sources)

    assert chosen == {source.id for source in sources}
    assert plan["intent"]["partitions"] == [
        "2022-12-31..2023-01-02",
        "2023-12-31..2024-01-02",
        "2024-12-31..2025-01-02",
    ]
    # Each occurrence holds its own Eve and its own New Year's Day.
    assert sorted(plan["intent_report"]["coverage"].values()) == [2, 2, 2]


@pytest.mark.feature("selection.local-time-dates")
def test_a_month_film_starts_and_ends_on_the_pictures_own_days(tmp_path):
    from immich_memories.memory_types.date_builders import build_month

    month = [picture(f"dec-{n:02}", datetime(2024, 12, 2 + n, 12)) for n in range(20)]
    # 07:00 on 1 December, ten hours ahead: still 30 November in UTC.
    first_morning = picture("first-of-december", datetime(2024, 12, 1, 7), AHEAD_10, favourite=True)
    # 07:00 on 1 January, ten hours ahead: still 31 December in UTC.
    next_month = picture("first-of-january", datetime(2025, 1, 1, 7), AHEAD_10, favourite=True)
    party = picture("eve-party", datetime(2024, 12, 31, 20, 30), BEHIND_8, favourite=True)

    chosen, plan = cut(
        tmp_path,
        "monthly_highlights",
        (build_month(12, 2024),),
        [*month, first_morning, next_month, party],
    )

    assert {"first-of-december", "eve-party"} <= chosen
    assert "first-of-january" not in chosen
    assert _story_day_of("first-of-december", plan) == "2024-12-01"
    assert _story_day_of("eve-party", plan) == "2024-12-31"


@pytest.mark.feature("selection.local-time-dates")
def test_a_birthday_film_holds_the_evening_party_of_the_day(tmp_path):
    from immich_memories.memory_types.date_builders import build_birthday_windows

    windows = tuple(build_birthday_windows(date(2015, 3, 14), 2024, years_back=0))
    year = [
        picture(f"y-{n:02}", datetime(2023, 4, 1, 12) + timedelta(days=15 * n)) for n in range(20)
    ]
    # The party at 20:30 on the birthday, eight hours behind UTC: 15 March in UTC.
    party = picture("party", datetime(2024, 3, 14, 20, 30), BEHIND_8, favourite=True)
    # The morning after, ten hours ahead: 14 March in UTC, but the day after the birthday.
    after = picture("morning-after", datetime(2024, 3, 15, 7), AHEAD_10, favourite=True)

    chosen, _plan = cut(tmp_path, "person_spotlight", windows, [*year, party, after])

    assert "party" in chosen
    assert "morning-after" not in chosen


class InstantFilteringImmich:
    """A fake Immich whose metadata search filters `takenAfter`/`takenBefore` on the UTC
    instant, as the real server does, and records every window it was asked for."""

    def __init__(self, pictures: list[Asset]) -> None:
        self.pictures = pictures
        self.windows: list[tuple[str, str]] = []

    def handler(self, request):
        import httpx

        if request.url.path.endswith("/server/version"):
            return httpx.Response(200, json={"major": 2, "minor": 7, "patch": 5})
        if not request.url.path.endswith("/search/metadata"):
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        after = datetime.fromisoformat(body["takenAfter"])
        before = datetime.fromisoformat(body["takenBefore"])
        self.windows.append((body["takenAfter"], body["takenBefore"]))
        items = [
            p.model_dump(mode="json", by_alias=True)
            for p in self.pictures
            if after <= p.file_created_at <= before and body.get("type") in (None, p.type.value)
        ]
        return httpx.Response(200, json={"assets": {"items": items, "total": len(items)}})


@pytest.mark.feature("selection.local-time-dates")
def test_a_year_fetch_reads_past_utc_and_keeps_the_pictures_own_year(monkeypatch):
    import httpx

    from immich_memories.api.sync_client import SyncImmichClient

    party = picture("eve-party", datetime(2024, 12, 31, 20, 30), BEHIND_8)
    breakfast = picture("new-year-breakfast", datetime(2025, 1, 1, 7), AHEAD_10)
    new_year_morning = picture("first-of-january", datetime(2024, 1, 1, 7), AHEAD_10)
    # A server that sent no local clock: the UTC instant, 1 January 2025, is all there is.
    unclocked = picture("no-clock", datetime(2024, 12, 31, 20, 30), BEHIND_8, local_clock=False)
    server = InstantFilteringImmich([party, breakfast, new_year_morning, unclocked])
    real_client = httpx.AsyncClient
    # WHY: the Immich HTTP boundary; requests go to the in-process fake server.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(server.handler), **kwargs),
    )
    client = SyncImmichClient("https://immich.example.test", "key-" * 8, api_version="v2")

    photos = client.get_photos_for_date_range(calendar_year(2024))
    everything = client.get_assets_for_date_range(calendar_year(2024))

    assert {p.id for p in photos} == {"eve-party", "first-of-january"}
    assert {p.id for p in everything} == {"eve-party", "first-of-january"}
    assert server.windows[0] == ("2023-12-31T10:00:00+00:00", "2025-01-01T13:59:59+00:00")


HOME = (45.0, 5.0)
FAR = (-30.0, 140.0)  # made-up spots far from the made-up home
WEST = (40.0, -100.0)


def _trips_of(year: int, pictures: list[Asset]):
    from unittest.mock import create_autospec

    from immich_memories.analysis.sources.trip_discovery import discover_year_trips
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.config.models.automation import TripsConfig

    # WHY: the Immich read boundary; the autospec refuses any call the real client would.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_assets_for_date_range.return_value = pictures
    config = TripsConfig(homebase_latitude=HOME[0], homebase_longitude=HOME[1])
    return discover_year_trips(client, config, year)


@pytest.mark.feature("selection.local-time-dates")
def test_a_trip_runs_from_its_first_to_its_last_day_on_the_pictures_own_clock():
    # Landed at 07:00 on 10 March ten hours ahead (9 March in UTC); a last dinner at 20:30
    # on 14 March eight hours behind (15 March in UTC).
    trip = [
        picture("arrival", datetime(2024, 3, 10, 7), AHEAD_10, where=FAR),
        picture("beach", datetime(2024, 3, 12, 15), AHEAD_10, where=FAR),
        picture("dinner", datetime(2024, 3, 14, 20, 30), BEHIND_8, where=WEST),
    ]

    (found,) = _trips_of(2024, trip)

    assert (found.start_date, found.end_date) == (date(2024, 3, 10), date(2024, 3, 14))


@pytest.mark.feature("selection.local-time-dates")
def test_a_trip_ending_on_new_years_eve_belongs_to_the_old_year_only():
    trip = [
        picture("first", datetime(2024, 12, 28, 10), BEHIND_8, where=WEST),
        picture("hike", datetime(2024, 12, 30, 10), BEHIND_8, where=WEST),
        picture("eve", datetime(2024, 12, 31, 20, 30), BEHIND_8, where=WEST),
    ]

    assert [t.end_date for t in _trips_of(2024, trip)] == [date(2024, 12, 31)]
    assert _trips_of(2025, trip) == []


@pytest.mark.feature("selection.local-time-dates")
def test_one_evening_behind_utc_is_one_photographed_day():
    """The run record says how many days a film holds; an evening is one, not two in UTC."""
    from immich_memories.planning.auto_duration import (
        DURATION_FROM_MATERIAL,
        decide_memory_duration,
    )

    # 15:00 and 20:30 on 31 December, eight hours behind: 31 December and 1 January in UTC.
    evening = [
        picture("afternoon", datetime(2024, 12, 31, 15), BEHIND_8),
        picture("party", datetime(2024, 12, 31, 20, 30), BEHIND_8),
    ]

    decision = decide_memory_duration(
        [],
        evening,
        requested_seconds=None,
        requested_source=DURATION_FROM_MATERIAL,
        preset_seconds=None,
        memory_type="custom",
        avg_clip_duration=5.0,
        photo_duration=4.0,
        title_duration=3.5,
        ending_duration=4.0,
    )

    assert decision.photographed_days == 1


@pytest.mark.feature("selection.local-time-dates")
def test_a_film_runs_in_the_order_its_pictures_clocks_show(tmp_path):
    """Order is the pictures' own clocks, the order Immich's timeline shows, and it holds
    however the offsets change inside the film."""
    summer, winter = timedelta(hours=2), timedelta(hours=1)
    days = [picture(f"day-{n:02}", datetime(2024, 10, 1 + n, 12), summer) for n in range(20)]
    # The clocks go back: 02:40 summer time, then 02:10 winter time half an hour later.
    before = picture("dst-before", datetime(2024, 10, 27, 2, 40), summer, favourite=True)
    after = picture("dst-after", datetime(2024, 10, 27, 2, 10), winter, favourite=True)
    far_east = picture("far-east", datetime(2024, 10, 28, 21), timedelta(hours=9), favourite=True)

    chosen, plan = cut(
        tmp_path,
        "monthly_highlights",
        (DateRange(datetime(2024, 10, 1), datetime(2024, 10, 31, 23, 59, 59)),),
        [*days, before, after, far_east],
    )

    order = [c["asset_id"] for c in plan["carriers"]]
    assert {"dst-before", "dst-after", "far-east"} <= chosen
    assert order.index("dst-after") < order.index("dst-before") < order.index("far-east")
    clocks = [c["taken"][:19] for c in plan["carriers"]]
    assert clocks == sorted(clocks)
