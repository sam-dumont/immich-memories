"""A film's length and its history count only the pictures a film may use.

A birthday film (then the year plus its earlier birthdays) asked for 245 s and filled 127 s: its length was sized on 36 photographed days,
half of them holding only forwarded copies (messaging exports with no camera behind them) that
every film refuses before it reads a picture (`film_may_use`). The same run said "history: 3 of
5 earlier windows hold material", and its earlier birthdays held nothing but such copies, so the
film showed none of them and nothing said why.
"""

from __future__ import annotations

from datetime import date, datetime

from immich_memories.analysis.selection_source_validation import film_may_use
from immich_memories.api.models import AssetType
from immich_memories.cli._asset_fetch import fetch_media
from immich_memories.cli._helpers import set_active_display
from immich_memories.cli.film_length import decide_duration
from immich_memories.config_loader import Config
from immich_memories.memory_types.date_builders import (
    BIRTHDAY_HISTORY_FROM,
    build_birthday_windows,
)
from tests.conftest import make_asset
from tests.test_birthday_memory import _PhotoLibrary, _RecordingDisplay


def _photo(asset_id: str, when: datetime, *, forwarded: bool):
    """A camera photo, or a messaging export: a UUID JPEG with no camera, 576x1024."""
    asset = make_asset(
        asset_id,
        file_created_at=when,
        original_file_name=(
            f"{asset_id[:8].ljust(8, '0')}-1111-2222-3333-444444444444.jpg"
            if forwarded
            else f"IMG_{asset_id}.HEIC"
        ),
        exif_make=None if forwarded else "Apple",
        exif_model=None if forwarded else "iPhone 15 Pro",
        duration=None,
    )
    return asset.model_copy(
        update={
            "type": AssetType.IMAGE,
            "width": 576 if forwarded else 4284,
            "height": 1024 if forwarded else 5712,
        }
    )


def test_a_forwarded_copy_is_no_picture_a_film_may_use():
    usable = film_may_use(Config())

    assert usable(_photo("cam", datetime(2025, 9, 1, 12), forwarded=False))
    assert not usable(_photo("fwd", datetime(2025, 9, 2, 12), forwarded=True))
    # A film told to take received media as the record takes it.
    assert film_may_use(Config(), accept_any_provenance=True)(
        _photo("fwd", datetime(2025, 9, 2, 12), forwarded=True)
    )


def test_a_films_length_is_sized_on_the_days_it_can_use():
    photos = [_photo("cam", datetime(2025, 9, 1, 12), forwarded=False)] + [
        _photo(f"fwd{day}", datetime(2025, 9, day, 12), forwarded=True) for day in range(2, 12)
    ]

    decision = decide_duration(
        None,
        requested_source=None,
        preset_duration=600.0,
        memory_type="person_spotlight",
        clips=[],
        photos=photos,
        config=Config(),
    )

    assert decision.photographed_days == 1


def test_earlier_birthdays_holding_only_forwarded_copies_hold_no_history():
    copies = [_photo(f"fwd{i}", datetime(2022, 2, 7, 10, i), forwarded=True) for i in range(3)]
    display = _RecordingDisplay()
    set_active_display(display)
    try:
        fetch_media(
            client=_PhotoLibrary(copies),
            progress=display,
            date_ranges=build_birthday_windows(date(2018, 2, 7), year=2026, years_back=5),
            person_ids=[],
            include_photos=True,
            history_from=BIRTHDAY_HISTORY_FROM,
            usable=film_may_use(Config()),
        )
    finally:
        set_active_display(None)
    out = "\n".join(display.lines)

    assert "history: 0 of 5 earlier windows hold material" in out
    assert "3 pictures there are forwarded copies or saved images, which no film uses" in out
    assert "the memory has no history" in out


def test_forwarded_copies_standing_in_count_toward_the_films_length():
    """With `analysis.forwarded_copies_when_short`, copies filling a gap are material."""
    from immich_memories.analysis.forwarded_fallback import CopyChecks
    from immich_memories.cli.film_length import sized_film
    from immich_memories.timeperiod import DateRange

    # September's camera picture is on the 1st; October holds copies only: a gap.
    photos = [_photo("cam", datetime(2025, 9, 1, 12), forwarded=False)] + [
        _photo(f"fwd{day}", datetime(2025, 10, day, 12), forwarded=True) for day in (2, 3)
    ]
    span = DateRange(datetime(2025, 9, 1), datetime(2025, 10, 31, 23, 59))
    wanted = {
        "requested_source": None,
        "preset_duration": 600.0,
        "memory_type": "person_spotlight",
        "clips": [],
        "photos": photos,
        "span": span,
        "windows": None,
        "accept_any_provenance": False,
        "checks": lambda _pool: CopyChecks(),
    }

    off, none = sized_film(None, config=Config(), **wanted)
    on_config = Config(analysis={"forwarded_copies_when_short": True})
    on, stand_ins = sized_film(None, config=on_config, **wanted)

    assert (off.photographed_days, none.ids) == (1, frozenset())
    # A film this short is read by the week: 2 and 3 October share one gap week, which takes
    # the one day a week with camera pictures holds, the earliest of two equal ones.
    assert stand_ins.ids == {"fwd2"}
    assert on.photographed_days == 2
