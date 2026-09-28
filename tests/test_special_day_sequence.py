"""A day is found by what it was, read beside the days around it, not by clearing a bar (#1093).

Every day below is generated. A day quiet on every axis but one (a camp day of eighteen pictures
across four hours) sits under both of the old bars; a busy ordinary day at home clears them.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from immich_memories.analysis.special_day import SpecialDay
from immich_memories.automation.special_day_scan import scan_year

# Synthetic coordinates: a home, and a camp about 67 km south of it.
HOME_AT = (50.8, 4.4)
CAMP_AT = (50.2, 4.4)


def _picture(when: datetime, n: int, *, city: str | None, video: float | None = None, at=None):
    lat, lon = at or (None, None)
    return SimpleNamespace(
        id=f"p-{when:%m%d%H%M}-{n}",
        file_created_at=when,
        exif_info=SimpleNamespace(
            city=city, country="Belgium" if city else None, latitude=lat, longitude=lon
        ),
        people=[],
        is_favorite=False,
        is_video=video is not None,
        duration_seconds=video,
        llm_description=None,
    )


def _day(start: datetime, *, pictures: int, hours: int, city: str | None, videos: int = 0, at=None):
    step = timedelta(hours=hours) / pictures
    return [
        _picture(start + step * n, n, city=city, video=8.0 if n < videos else None, at=at)
        for n in range(pictures)
    ]


CAMP = datetime(2021, 7, 14, 10, 0, tzinfo=UTC)
HOME = datetime(2021, 7, 3, 9, 0, tzinfo=UTC)


def _library():
    camp = _day(CAMP, pictures=18, hours=4, city="Hastière", videos=3, at=CAMP_AT)
    home = _day(HOME, pictures=60, hours=9, city="Someplace", at=HOME_AT)
    captions = {p.id: "children around a campfire at a summer camp" for p in camp}
    captions |= {p.id: "a cat asleep on a sofa" for p in home}
    return camp + home, captions


class Reader:
    # WHY: the text model is the only external boundary. It names the days whose evidence
    # line mentions a camp, the way a reader comparing the month's days would.
    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        named = [
            {"run": run, "what": "a summer camp"}
            for run, line in re.findall(r"^(R\d+) \| (.*)$", prompt, re.MULTILINE)
            if "camp" in line
        ]
        return json.dumps({"occasions": named})


@pytest.fixture
def reader(monkeypatch):
    read = Reader()
    monkeypatch.setattr("immich_memories.analysis.special_day_sequence._read", read)
    # WHY: the day-level model confirms the camp; which days reach it is the subject.
    monkeypatch.setattr(
        "immich_memories.automation.special_day_scan.ask_if_special",
        lambda *_a, **_k: SpecialDay(special=True, title="Camp", what="a camp"),
    )
    return read


def test_a_day_under_every_bar_is_found_by_what_it_was(reader):
    assets, captions = _library()

    found = scan_year(assets, llm_config=None, home=None, captions=captions)

    assert [d.day for d in found] == [CAMP.date()]
    # Both days reached the reader, side by side in one reading of their month.
    assert len(reader.prompts) == 1
    assert "summer camp" in reader.prompts[0] and "cat asleep" in reader.prompts[0]


def test_the_days_own_evidence_must_confirm_the_proposed_occasion(reader, monkeypatch):
    assets, captions = _library()
    # WHY: the day-level model disagrees with the month-level model's proposed occasion.
    monkeypatch.setattr(
        "immich_memories.automation.special_day_scan.ask_if_special",
        lambda *_a, **_k: SpecialDay(special=False, title="An afternoon outside", what="a walk"),
    )

    found = scan_year(assets, llm_config=None, home=None, captions=captions)

    assert len(reader.prompts) == 1
    assert found == []


def test_an_occasion_a_film_cannot_be_cut_from_is_dropped_at_the_end(reader, caplog):
    # Three pictures in one burst read as a camp: correctly named, and unshowable.
    burst = _day(CAMP, pictures=3, hours=1, city="Hastière")
    # A photo-only camp of three episodes a morning, an afternoon and an evening apart.
    spread = [
        p
        for start in (10, 14, 19)
        for p in _day(CAMP.replace(day=21, hour=start), pictures=5, hours=1, city="Hastière")
    ]
    captions = {p.id: "children around a campfire at a summer camp" for p in burst + spread}

    with caplog.at_level("INFO"):
        found = scan_year(burst + spread, llm_config=None, home=None, captions=captions)

    assert [d.day for d in found] == [date(2021, 7, 21)]
    assert "2021-07-14 read as 'a summer camp', dropped for want of material" in caplog.text


def test_a_run_with_no_place_says_so_and_one_with_nothing_recorded_is_not_offered(reader):
    unplaced = _day(CAMP, pictures=18, hours=4, city=None)
    blank = _day(CAMP.replace(day=20), pictures=40, hours=8, city=None)
    captions = {p.id: "children around a campfire at a summer camp" for p in unplaced}

    scan_year(unplaced + blank, llm_config=None, home=None, captions=captions)

    (prompt,) = reader.prompts
    assert "place: not recorded" in prompt
    assert "Tue 20 Jul" not in prompt
    # The question comes after the evidence, never before it.
    assert prompt.index("summer camp") < prompt.index("Which of these days were occasions")


def test_a_month_the_reader_could_not_read_leaves_the_year_unscanned(monkeypatch):
    from immich_memories.automation.special_day_scan import YearNotRead

    assets, captions = _library()
    # WHY: the text model, down for this call.
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no route to host")),
    )

    with pytest.raises(YearNotRead, match="2021-07"):
        scan_year(assets, llm_config=None, home=None, captions=captions)


def test_a_run_the_reader_invents_is_ignored(monkeypatch, reader):
    assets, captions = _library()
    # WHY: the text model, naming a run nobody offered it.
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R9", "what": "a wedding"}]}),
    )

    assert scan_year(assets, llm_config=None, home=None, captions=captions) == []


@pytest.fixture
def no_model(monkeypatch):
    # WHY: the text model is the boundary; the no-model tier must never reach it.
    def refuse(*_a, **_k):
        pytest.fail("the no-model tier asked a model")

    monkeypatch.setattr("immich_memories.analysis.special_day_sequence._read", refuse)
    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", refuse)


# The people file's close family, by Immich person id: roles only ever reach a line.
FAMILY = {"p-owner": "owner", "p-partner": "partner", "p-son": "son"}


def _with(pictures, *person_ids):
    for picture in pictures:
        picture.people = [SimpleNamespace(id=pid, name="A Person") for pid in person_ids]
    return pictures


def test_without_a_model_days_are_found_from_their_facts_alone(no_model):
    """The NAS tier (`editorial.reader: rules`, no model) discovers days with no text call.

    The camp was spent 67 km from home: loud on its own, with nobody in the family on it. The
    busy day at home clears the old active-hours bar with nobody in it, and the bar alone
    no longer finds a day at home (#1220).
    """
    assets, captions = _library()

    found = scan_year(
        assets,
        llm_config=None,
        home=HOME_AT,
        captions=captions,
        reader="rules",
        close_family=FAMILY,
    )

    assert {d.day: (d.what, d.title) for d in found} == {
        CAMP.date(): ("a day away from home", "A day in Hastière"),
    }


def test_without_a_model_a_long_day_at_home_with_the_family_is_found(no_model):
    party = _day(HOME, pictures=60, hours=9, city="Someplace", at=HOME_AT)
    _with(party[:30], "p-partner", "p-son")
    _with(party[30:40], "p-neighbour")

    found = scan_year(party, llm_config=None, home=HOME_AT, reader="rules", close_family=FAMILY)

    assert [d.what for d in found] == ["a long day with close family, 9 active hours"]


def test_the_line_says_which_close_family_were_there_by_role_only(reader):
    assets, captions = _library()
    camp = [a for a in assets if a.file_created_at.date() == CAMP.date()]
    _with(camp[:6], "p-son")
    _with(camp[6:9], "p-owner", "p-partner")

    scan_year(assets, llm_config=None, home=None, captions=captions, close_family=FAMILY)

    (prompt,) = reader.prompts
    assert "close family: owner, partner, son on 9 of 18 pictures" in prompt
    assert "p-son" not in prompt


@pytest.mark.parametrize(
    ("starred", "videos", "what"),
    [(3, 0, "3 favourites"), (0, 6, "a day mostly on video"), (2, 2, None)],
)
def test_without_a_model_one_loud_fact_is_enough(starred, videos, what):
    # Twelve pictures in three episodes of one afternoon at home: under the hours bar.
    day = [
        p
        for start in (12, 15, 18)
        for p in _day(HOME.replace(hour=start), pictures=4, hours=1, city="Someplace")
    ]
    for picture in day[:starred]:
        picture.is_favorite = True
    for picture in day[-videos:] if videos else []:
        picture.is_video, picture.duration_seconds = True, 8.0

    found = scan_year(day, llm_config=None, home=None, reader="rules")

    assert [d.what for d in found] == ([what] if what else [])


def _thirty_loud_days():
    """Thirty runs in one year, each loud on one fact, with strengths that rank them."""
    runs = []
    for n in range(30):
        start = datetime(2021, 1 + n // 3, 3 + (n % 3) * 9, 10, tzinfo=UTC)
        spread = [
            p
            for hour in (0, 3, 6)
            for p in _day(start + timedelta(hours=hour), pictures=4, hours=1, city="Someplace")
        ]
        kind = n % 3
        if kind == 0:  # away from home, further each time
            for p in spread:
                p.exif_info.latitude, p.exif_info.longitude = HOME_AT[0] - 0.5 - n / 100, HOME_AT[1]
        elif kind == 1:  # favourites, more each time
            for p in spread[: 3 + n // 3]:
                p.is_favorite = True
        else:  # a long family day at home
            spread = _day(start, pictures=24, hours=8, city="Someplace", at=HOME_AT)
            _with(spread[: 4 + n // 3], "p-son")
        runs.append((n, kind, spread))
    return runs


def test_without_a_model_a_year_yields_its_strongest_few(no_model):
    runs = _thirty_loud_days()
    assets = [p for _n, _k, day in runs for p in day]

    found = scan_year(
        assets, llm_config=None, home=HOME_AT, reader="rules", close_family=FAMILY, per_year=6
    )

    # Away days rank first, the furthest first; ten of them are loud that way.
    furthest = sorted((n for n, kind, _ in runs if kind == 0), reverse=True)[:6]
    expected = {runs[n][2][0].file_created_at.date() for n in furthest}
    assert {d.day for d in found} == expected
    assert {d.what for d in found} == {"a day away from home"}


def test_the_model_tier_is_not_capped_by_the_shortlist(reader):
    days = [
        _day(
            datetime(2021, 1 + n // 3, 3 + (n % 3) * 9, 10, tzinfo=UTC),
            pictures=18,
            hours=4,
            city="Hastière",
            videos=3,
        )
        for n in range(30)
    ]
    captions = {p.id: "children at a summer camp" for day in days for p in day}

    found = scan_year(
        [p for d in days for p in d], llm_config=None, home=None, captions=captions, per_year=6
    )

    assert len(found) == 30


def test_a_run_is_described_by_where_its_pictures_are_not_by_its_first_hour():
    """A race day (09-28): three cat pictures at home before leaving, a hundred at the circuit,
    two more at home at night. The line quoted the cat twice and never the circuit, so the
    reader called it an ordinary day."""
    from immich_memories.analysis.special_day_sequence import run_line

    start = datetime(2030, 4, 7, 7, tzinfo=UTC)
    home = [_picture(start + timedelta(minutes=n), n, city="Home") for n in range(3)]
    circuit = _day(start + timedelta(hours=2), pictures=100, hours=2, city="Circuit")
    night = [
        _picture(start + timedelta(hours=10, minutes=n), 200 + n, city="Home") for n in range(2)
    ]
    captions = {a.id: f"A tabby cat on the stairs, number {i}" for i, a in enumerate(home + night)}
    captions |= {a.id: f"A race car on the track, lap {i}" for i, a in enumerate(circuit)}

    line = run_line("R1", [*home, *circuit, *night], captions)

    written = line.split("written: ", 1)[1]
    assert written.count("race car") >= 2


def test_a_day_that_contains_an_occasion_is_judged_on_the_occasion(monkeypatch):
    """A race day (09-28): the cat at home before leaving, two hours at a circuit 67 km away
    holding most of the day's pictures, home again at night. The small reader, shown the whole
    day, named it after the cat and called it ordinary. The place alone says where the day was
    spent, so an ordinary verdict is asked once more about that stretch."""
    start = datetime(2021, 4, 4, 7, tzinfo=UTC)
    morning = _day(start, pictures=6, hours=1, city="Someplace", at=HOME_AT)
    circuit = _day(start + timedelta(hours=2), pictures=60, hours=2, city="Hastière", at=CAMP_AT)
    evening = _day(start + timedelta(hours=10), pictures=5, hours=1, city="Someplace", at=HOME_AT)
    captions = {p.id: "a tabby cat on the stairs" for p in morning + evening}
    captions |= {p.id: "a race car on the track" for p in circuit}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R1", "what": "race track"}]}),
    )
    asked = []

    # WHY: the day-level model is the text boundary. Like the small reader, it calls a day
    # ordinary whenever the cat at home is in front of it.
    def day_reader(items, *_a, **_k):
        asked.append(len(items))
        if any(item in morning + evening for item in items):
            return SpecialDay(special=False, title="Cat on Staircase", what="a cat")
        return SpecialDay(special=True, title="Track Day", what="a race track")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)
    # WHY: the day fell on Easter; the holiday question is the same text boundary.
    monkeypatch.setattr(
        "immich_memories.automation.special_day_scan.was_the_holiday", lambda *_a, **_k: False
    )

    found = scan_year(morning + circuit + evening, llm_config=None, home=HOME_AT, captions=captions)

    assert [(d.day, d.title) for d in found] == [(date(2021, 4, 4), "Track Day")]
    assert asked == [71, 60]


def _forwarded(start: datetime, *, pictures: int, hours: int) -> list:
    sent = _day(start + timedelta(minutes=1), pictures=pictures, hours=hours, city=None)
    for picture in sent:
        picture.id = f"sent-{picture.id}"
    return sent


def _from_the_camera(pictures: list) -> list:
    from immich_memories.api.models import AssetType

    for picture in pictures:
        picture.exif_info.make = "Apple"
        picture.type = AssetType.IMAGE
        picture.live_photo_video_id = None
        picture.original_file_name = f"IMG_{picture.id}.HEIC"
    return pictures


def _sent(pictures: list) -> list:
    from immich_memories.api.models import AssetType

    for picture in pictures:
        picture.exif_info.make = None
        picture.type = AssetType.IMAGE
        picture.live_photo_video_id = None
        picture.original_file_name = f"received_{picture.id}.jpeg"
    return pictures


def test_a_day_whose_words_stand_out_reaches_the_day_check_the_month_reading_missed(monkeypatch):
    """An obstacle race (09-28): the owner's camera wrote "a runner on a path", as on every other
    run of the year, and the 123 pictures saved from the race's photographers wrote "obstacle
    race". The month reading proposed nothing; the words the year never uses propose the day."""
    from immich_memories.config_models_analysis import AnalysisConfig

    race = datetime(2021, 10, 17, 9, tzinfo=UTC)
    own = _from_the_camera(_day(race, pictures=25, hours=5, city="Somewhere"))
    sent = _sent(_forwarded(race, pictures=40, hours=5))
    only_sent = _sent(_forwarded(datetime(2021, 10, 3, 9, tzinfo=UTC), pictures=40, hours=5))
    # Saved together, stamped with one second: inside the camera's own run that day, and after it.
    batch = _sent(_forwarded(race, pictures=3, hours=1))
    for picture in batch:
        picture.id = f"batch-{picture.id}"
        picture.file_created_at = datetime(2021, 10, 17, 12, 0, 7, tzinfo=UTC)
    late = _sent(_forwarded(race.replace(hour=20), pictures=3, hours=1))
    for picture in late:
        picture.id = f"late-{picture.id}"
        picture.file_created_at = datetime(2021, 10, 17, 20, 0, 7, tzinfo=UTC)
    runs = [
        _from_the_camera(
            _day(datetime(2021, 9, day, 9, tzinfo=UTC), pictures=25, hours=5, city="Somewhere")
        )
        for day in (5, 12, 19, 26)
    ]
    # A year to stand out from: a run most weeks, written about the same way.
    runs += [
        _from_the_camera(
            [
                _picture(
                    datetime(2021, 1, 1, 9, tzinfo=UTC) + timedelta(weeks=w), w, city="Somewhere"
                )
            ]
        )
        for w in range(36)
    ]
    captions = {p.id: "a runner on a cobblestone path" for p in own + [p for r in runs for p in r]}
    captions |= {
        p.id: "runners in an obstacle race under the sponsor arch" for p in sent + only_sent
    }
    # The race's own photographs say the most; the batch saved after the run says the same.
    captions |= {
        p.id: "a finisher with a medal under the sponsor arch at the obstacle race finish"
        for p in batch + late
    }
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": []}),
    )
    asked = {}

    # WHY: the day-level model is the text boundary; what reaches it is the subject.
    def day_reader(items, *_a, forwarded=(), **_k):
        asked[items[0].file_created_at.date()] = {p.id for p in forwarded}
        return SpecialDay(special=True, title="Obstacle race", what="a race")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)

    found = scan_year(
        own + sent + only_sent + batch + late + [p for r in runs for p in r],
        llm_config=None,
        home=None,
        captions=captions,
        analysis_config=AnalysisConfig(),
    )

    assert [(d.day, d.photos) for d in found] == [(date(2021, 10, 17), 25)]
    assert asked == {date(2021, 10, 17): {p.id for p in batch}}


def test_a_day_on_a_holiday_is_kept_unless_its_occasion_was_the_holiday(monkeypatch):
    """A cycling race (09-28) fell on the date the list calls Father's Day, in the owner's own
    city, and was skipped as a holiday spent at home. The day is judged first; only then is its
    occasion asked whether it was the holiday itself."""
    race = _day(datetime(2023, 6, 18, 6, tzinfo=UTC), pictures=30, hours=6, city="Home", at=HOME_AT)
    christmas = _day(
        datetime(2023, 12, 25, 10, tzinfo=UTC), pictures=30, hours=6, city="Home", at=HOME_AT
    )
    captions = {p.id: "cyclists racing through the city" for p in race}
    captions |= {p.id: "a family opening presents by the christmas tree" for p in christmas}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": []}),
    )

    # WHY: the day-level model is the text boundary; it calls both days occasions.
    def day_reader(items, *_a, **_k):
        if items[0] in race:
            return SpecialDay(special=True, title="City bike race", what="a cycling race")
        return SpecialDay(special=True, title="Christmas morning", what="opening presents")

    asked = []

    # WHY: the holiday question is the same text boundary, asked only of holiday occasions.
    def holiday_reader(holiday, title, *_a, **_k):
        asked.append((holiday, title))
        return title == "Christmas morning"

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)
    monkeypatch.setattr(
        "immich_memories.automation.special_day_scan.was_the_holiday", holiday_reader
    )

    found = scan_year(race + christmas, llm_config=None, home=HOME_AT, captions=captions)

    assert [(d.day, d.title) for d in found] == [(date(2023, 6, 18), "City bike race")]
    assert sorted(asked) == [
        ("Christmas Day", "Christmas morning"),
        ("Father's Day", "City bike race"),
    ]


def test_a_day_counts_its_pictures_not_the_files_they_are_stored_in(monkeypatch):
    """A shared album stores a curated picture twice (09-28): the camera's file and a smaller copy,
    same name, same instant. Discovery counted both, so a day looked twice its size."""
    from immich_memories.api.models import AssetType

    pictures = _day(datetime(2021, 7, 3, 9, tzinfo=UTC), pictures=20, hours=5, city="Somewhere")
    copies = _day(datetime(2021, 7, 3, 9, tzinfo=UTC), pictures=20, hours=5, city="Somewhere")
    for original, copy in zip(pictures, copies, strict=True):
        for file, pixels in ((original, 4000), (copy, 2048)):
            file.type = AssetType.IMAGE
            file.original_file_name = f"IMG_{original.id}.HEIC"
            file.width = file.height = pixels
        copy.id = f"copy-{original.id}"
    copies[0].is_favorite = True
    captions = {p.id: "children around a campfire at a summer camp" for p in pictures + copies}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R1", "what": "a camp"}]}),
    )
    judged = []

    # WHY: the day-level model is the text boundary; what reaches it is the subject.
    def day_reader(items, *_a, **_k):
        judged.extend(items)
        return SpecialDay(special=True, title="Camp", what="a camp")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)

    found = scan_year(pictures + copies, llm_config=None, home=None, captions=captions)

    assert [d.photos for d in found] == [20]
    assert not any(item.id.startswith("copy-") for item in judged)
    assert any(item.is_favorite for item in judged)


def test_a_day_is_named_by_its_moment_not_by_everything_it_held(monkeypatch):
    """A concert night (09-28): the reader, shown the whole day, called it an occasion and named
    it after the baby at home. The words its weeks never write gather between seven and ten in
    the evening; asked about those hours, it names the concert."""
    home = [
        _day(datetime(2024, 10, day, 8, tzinfo=UTC), pictures=12, hours=6, city="Home", at=HOME_AT)
        for day in range(1, 14)  # before Columbus Day, a US holiday that would ask its own question
    ]
    concert_day = datetime(2024, 10, 3, 8, tzinfo=UTC)
    morning = _day(concert_day, pictures=20, hours=5, city="Home", at=HOME_AT)
    evening = _day(concert_day.replace(hour=19), pictures=30, hours=3, city="Home", at=HOME_AT)
    for picture in evening:
        picture.id = f"evening-{picture.id}"
    everyday = [p for d in home for p in d if p.file_created_at.day != 3]
    captions = {p.id: "a baby lying on a blanket" for p in everyday + morning}
    captions |= {p.id: "a singer performing on stage under bright lights" for p in evening}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R3", "what": "a concert"}]}),
    )
    asked = []

    # WHY: the day-level model is the text boundary; shown everything, it names the baby.
    def day_reader(items, *_a, **_k):
        asked.append(len(items))
        if any(item in morning for item in items):
            return SpecialDay(special=True, title="A day with the baby", what="baby and a show")
        return SpecialDay(special=True, title="A night of music", what="a concert")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)

    found = scan_year(everyday + morning + evening, llm_config=None, home=None, captions=captions)

    night = next(d for d in found if d.day == date(2024, 10, 3))
    assert night.title == "A night of music"
    assert asked[-2:] == [50, 30]


def test_a_moment_never_makes_an_ordinary_day_an_occasion(monkeypatch):
    """Asked alone, the moment of an ordinary day came back an occasion too often (09-28): a
    replay gained eleven weak days that way. A moment only renames a confirmed day."""
    home = [
        _day(datetime(2024, 10, day, 8, tzinfo=UTC), pictures=12, hours=6, city="Home", at=HOME_AT)
        for day in range(1, 14)  # before Columbus Day, a US holiday that would ask its own question
    ]
    concert_day = datetime(2024, 10, 3, 8, tzinfo=UTC)
    morning = _day(concert_day, pictures=20, hours=5, city="Home", at=HOME_AT)
    evening = _day(concert_day.replace(hour=19), pictures=30, hours=3, city="Home", at=HOME_AT)
    for picture in evening:
        picture.id = f"evening-{picture.id}"
    everyday = [p for d in home for p in d if p.file_created_at.day != 3]
    captions = {p.id: "a baby lying on a blanket" for p in everyday + morning}
    captions |= {p.id: "a singer performing on stage under bright lights" for p in evening}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R3", "what": "a concert"}]}),
    )
    asked = []

    # WHY: the day-level model is the text boundary; shown everything, it names the baby.
    def day_reader(items, *_a, **_k):
        asked.append(len(items))
        if any(item in morning for item in items):
            return SpecialDay(special=False, title="A day with the baby", what="baby and a show")
        return SpecialDay(special=True, title="A night of music", what="a concert")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)

    found = scan_year(everyday + morning + evening, llm_config=None, home=None, captions=captions)

    assert date(2024, 10, 3) not in {d.day for d in found}
    assert 30 not in asked


def test_a_day_whose_title_already_names_what_stood_out_keeps_it(monkeypatch):
    """ "Night of the Haunted Youth" came back "Under Purple Lights" (09-28): the band's name was
    in the day's title, and the moment's reading lost it. A title that already names the day's
    own unusual words is not asked again."""
    home = [
        _day(datetime(2024, 10, day, 8, tzinfo=UTC), pictures=12, hours=6, city="Home", at=HOME_AT)
        for day in range(1, 14)  # before Columbus Day, a US holiday that would ask its own question
    ]
    concert_day = datetime(2024, 10, 3, 8, tzinfo=UTC)
    morning = _day(concert_day, pictures=20, hours=5, city="Home", at=HOME_AT)
    evening = _day(concert_day.replace(hour=19), pictures=30, hours=3, city="Home", at=HOME_AT)
    for picture in evening:
        picture.id = f"evening-{picture.id}"
    everyday = [p for d in home for p in d if p.file_created_at.day != 3]
    captions = {p.id: "a baby lying on a blanket" for p in everyday + morning}
    captions |= {p.id: "a singer performing on stage under bright lights" for p in evening}
    monkeypatch.setattr(
        "immich_memories.analysis.special_day_sequence._read",
        lambda *_a, **_k: json.dumps({"occasions": [{"run": "R3", "what": "a concert"}]}),
    )
    asked = []

    # WHY: the day-level model is the text boundary; its whole-day title names the stage.
    def day_reader(items, *_a, **_k):
        asked.append(len(items))
        return SpecialDay(special=True, title="The singer on stage", what="an evening show")

    monkeypatch.setattr("immich_memories.automation.special_day_scan.ask_if_special", day_reader)

    found = scan_year(everyday + morning + evening, llm_config=None, home=None, captions=captions)

    assert next(d for d in found if d.day == date(2024, 10, 3)).title == "The singer on stage"
    assert 30 not in asked
