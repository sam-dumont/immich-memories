"""Discovery asks about the days of a year together, saves a year once and reads the year's words once."""

from __future__ import annotations

import threading
from collections import Counter
from datetime import UTC, date, datetime
from types import SimpleNamespace

from immich_memories.analysis.special_days.detection import SpecialDay
from immich_memories.automation.special_day_scan import scan_year
from immich_memories.config.models.llm import LLMConfig
from tests.test_special_day_sequence import _day, reader  # noqa: F401 - the fixture


def _camp_days(count):
    days = [
        _day(
            datetime(2021, 1 + n // 3, 3 + (n % 3) * 9, 10, tzinfo=UTC),
            pictures=18,
            hours=4,
            city="Hastière",
            videos=3,
        )
        for n in range(count)
    ]
    captions = {p.id: "children at a summer camp" for day in days for p in day}
    return [p for day in days for p in day], captions


def _llm(concurrency):
    return LLMConfig(
        enabled=True,
        base_url="https://api.openai.com/v1",
        provider="openai",
        model="test-reader",
        reader_concurrency=concurrency,
    )


def _scan(monkeypatch, concurrency, *, barrier=None):
    """One scan whose day check can be held until several days are asking at once."""
    seen = Counter[str]()
    active = 0
    most = 0
    lock = threading.Lock()

    def ask(pictures, *_args, **_kwargs):
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        if barrier is not None:
            try:
                barrier.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass
        with lock:
            seen["asked"] += 1
            active -= 1
        first = min(p.file_created_at for p in pictures)
        return SpecialDay(special=True, title=f"Camp {first:%m-%d}", what="a camp")

    # WHY: the day-level model is the one outside call; the scan, its reader pool and ordering are real.
    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", ask)
    assets, captions = _camp_days(8)
    found = scan_year(assets, llm_config=_llm(concurrency), home=None, captions=captions)
    return found, most, seen["asked"]


def test_the_days_of_a_year_are_asked_together_and_come_back_in_the_same_order(
    reader,  # noqa: F811
    monkeypatch,
):
    serial, serial_most, serial_asked = _scan(monkeypatch, 1)
    together, most, asked = _scan(monkeypatch, 4, barrier=threading.Barrier(4))

    assert serial_most == 1
    assert most == 4
    assert asked == serial_asked == 8
    assert together == serial
    assert [d.day for d in together] == sorted(d.day for d in together)


def test_a_year_is_saved_once_with_its_days_and_its_marker(monkeypatch):
    from immich_memories.cli import special_days_cmd

    days = [
        SimpleNamespace(day=date(2021, 1, n), judged=True, title=f"Day {n}", what="")
        for n in range(1, 6)
    ]
    saved: list[list[dict]] = []
    monkeypatch.setattr(special_days_cmd, "save_catalogue", lambda rows: saved.append(list(rows)))
    monkeypatch.setattr(special_days_cmd, "record_for", lambda day: {"day": day.day.isoformat()})
    monkeypatch.setattr(
        "immich_memories.automation.special_day_scan.scan_year", lambda *_a, **_k: days
    )
    monkeypatch.setattr(
        "immich_memories.analysis.preparation.prepared_captions.prepared_captions",
        lambda *_a: {},
    )
    monkeypatch.setattr("immich_memories.cache.judgment_cache.judgment_bank", lambda _c: None)
    monkeypatch.setattr("immich_memories.home_country.home_country", lambda _c: "BE")
    monkeypatch.setattr(special_days_cmd, "_close_family", dict)
    config = SimpleNamespace(
        llm=SimpleNamespace(model="m"),
        analysis=None,
        trips=None,
        photos=SimpleNamespace(duration=4.0),
        editorial=SimpleNamespace(resolve_reader=lambda _m: "rules"),
        automation=SimpleNamespace(special_days_per_year=6),
    )
    found: list[dict] = [{"scanned": 2020}]

    special_days_cmd._scan_one_year(2021, [SimpleNamespace(id="a")], found, (), None, config)

    assert len(saved) == 1
    assert saved[0] == [
        {"scanned": 2020},
        *({"day": f"2021-01-0{n}"} for n in range(1, 6)),
        {"scanned": 2021},
    ]


def test_the_years_words_are_counted_once_however_many_days_ask_what_stands_out(monkeypatch):
    from immich_memories.analysis.special_days import vocabulary

    pictures = [SimpleNamespace(id=f"p{n}") for n in range(6)]
    captions = {
        p.id: f"a {'red' if n % 2 else 'blue'} kite number {n} on the beach"
        for n, p in enumerate(pictures)
    }
    said = {date(2021, 5, d): [captions[p.id] for p in pictures[:3]] for d in range(1, 8)}
    year = vocabulary.year_vocabulary(said)
    counted = Counter[str]()
    real = vocabulary._year_of

    def counting(*args):
        counted["years"] += 1
        return real(*args)

    monkeypatch.setattr(vocabulary, "_year_of", counting)

    alone = [vocabulary.telling(pictures, captions, said, keep=3) for _ in range(5)]
    together = [vocabulary.telling(pictures, captions, said, keep=3, year=year) for _ in range(5)]

    assert alone == together
    assert counted["years"] == 5
