"""A film's Immich description and tags, built from the run's own facts (#2505)."""

from __future__ import annotations

from datetime import date

from immich_memories.api.film_label import film_label

KIT = {"title": "Kit's birthday", "occasion": "birthday", "trip": None}
VISIT = {"title": "Lou and Pat's visit", "occasion": "visit", "trip": None}
ROAD = {"title": "The road north", "occasion": "trip", "trip": "The road north"}
SUMMARY = "Kit's birthday, then Lou and Pat's visit, then The road north"


def label(**overrides):
    facts = {
        "title": "July 2025",
        "summary": SUMMARY,
        "type_label": "Monthly highlights",
        "date_start": date(2025, 7, 1),
        "date_end": date(2025, 7, 31),
        "episodes": [KIT, VISIT, ROAD],
    }
    return film_label(**(facts | overrides))


def test_description_joins_title_and_summary():
    assert label().description == f"July 2025 · {SUMMARY}"


def test_description_without_summary_is_the_title():
    assert label(summary=None).description == "July 2025"
    assert label(summary="  ").description == "July 2025"


def test_description_without_title_is_the_summary():
    assert label(title=None).description == SUMMARY


def test_no_title_and_no_summary_sets_no_description():
    assert label(title="", summary=None).description is None


def test_summary_equal_to_the_title_is_written_once():
    assert label(title="The road north", summary="the road north ").description == "The road north"


def test_tags_carry_type_year_and_stories_under_the_root():
    assert label().tags == (
        "immich-memories/type/Monthly highlights",
        "immich-memories/year/2025",
        "immich-memories/story/Kit's birthday",
        "immich-memories/story/Lou and Pat's visit",
        "immich-memories/story/The road north",
    )


def test_a_range_over_new_year_tags_both_years():
    tags = label(date_start=date(2024, 12, 20), date_end=date(2025, 1, 10)).tags
    assert "immich-memories/year/2024" in tags
    assert "immich-memories/year/2025" in tags


def test_a_multi_year_range_tags_every_year_between():
    tags = label(date_start=date(2022, 6, 1), date_end=date(2025, 6, 1)).tags
    assert [t for t in tags if "/year/" in t] == [
        f"immich-memories/year/{year}" for year in (2022, 2023, 2024, 2025)
    ]


def test_legs_of_one_trip_make_one_story_tag_from_the_trip_name():
    legs = [
        {"title": "Oslo", "occasion": "leg", "trip": "Nordkapp"},
        {"title": "Oslo to Tromso", "occasion": "leg", "trip": "Nordkapp"},
    ]
    tags = label(episodes=legs).tags
    assert [t for t in tags if "/story/" in t] == ["immich-memories/story/Nordkapp"]


def test_a_story_that_is_no_named_occasion_gets_no_tag():
    home = {"title": "Days at home", "occasion": None, "trip": None}
    event = {"title": "A concert", "occasion": "event", "trip": None}
    assert not [t for t in label(episodes=[home, event]).tags if "/story/" in t]


def test_slashes_in_names_do_not_make_extra_levels():
    tags = label(episodes=[{"title": "Mum/Dad's visit", "occasion": "visit"}]).tags
    assert "immich-memories/story/MumDad's visit" in tags
    assert label(type_label="A/B").tags[0] == "immich-memories/type/AB"


def test_missing_pieces_leave_out_only_their_tags():
    bare = label(type_label=None, date_start=None, date_end=None, episodes=[])
    assert bare.tags == ()
    assert bare.description is not None


def test_a_name_that_is_only_slashes_is_dropped():
    assert not [
        t for t in label(episodes=[{"title": "//", "occasion": "visit"}]).tags if "story" in t
    ]


# A person film's plan, as the planner writes it: `chosen` holds the shots a story put in the
# cut, `days` its first and last day. A birthdays film's windows reach years back.
SHOWN_2022 = {
    "title": "Kit's birthday",
    "occasion": "birthday",
    "chosen": ["M1"],
    "days": ["2022-08-30", "2022-08-30"],
}
SHOWN_2025 = {
    "title": "A day at home",
    "occasion": None,
    "chosen": ["M2", "M3"],
    "days": ["2025-12-31", "2026-01-01"],
}
LEFT_OUT_2024 = {
    "title": "Lou and Pat's visit",
    "occasion": "visit",
    "chosen": [],
    "days": ["2024-05-04", "2024-05-04"],
}


def test_years_are_the_years_the_films_shots_show_not_its_whole_window():
    # WHY: a birthday film over 2021-2026 was tagged 2021 and 2024, which it never shows.
    tags = label(
        date_start=date(2021, 8, 29),
        date_end=date(2026, 8, 30),
        episodes=[SHOWN_2022, SHOWN_2025, LEFT_OUT_2024],
    ).tags
    assert [t for t in tags if "/year/" in t] == [
        f"immich-memories/year/{year}" for year in (2022, 2025, 2026)
    ]


def test_a_story_the_cut_left_out_gets_no_tag():
    tags = label(episodes=[SHOWN_2022, LEFT_OUT_2024]).tags
    assert [t for t in tags if "/story/" in t] == ["immich-memories/story/Kit's birthday"]
