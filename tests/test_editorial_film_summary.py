"""A film says what its period was about, from its own stories, on every tier (#2488).

The stories are stand-ins in the record shape the rules reader writes (#2486 contract): the
demo month's answer key in `tests/e2e/fake_library.py`, with its trip split into legs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from immich_memories.analysis.editorial_film_summary import (
    plain_summary,
    read_summary,
    summarise_the_film,
)
from immich_memories.analysis.editorial_story_names import home_name
from immich_memories.analysis.editorial_story_reading import PeriodStory
from immich_memories.analysis.editorial_thin_step import polish_the_draft
from tests.e2e.fake_library import STORY_BY_KEY, TRIP_DAYS

BIRTHDAY = STORY_BY_KEY["S0001"]
TRIP = STORY_BY_KEY["S0002"]
FOREST = STORY_BY_KEY["S0003"]
HOME = STORY_BY_KEY["S0004"]

# What the period account (a navigation note, not a film summary) said of the demo month.
NAVIGATION_NOTE = (
    "Birthday party at home in Brussels; a long drive through Denmark, Sweden and Norway. "
    "The broad pattern is home days followed by road travel."
)
FULL_REPLY = (
    "July was Kit's birthday at home, then twenty days on the road north to Nordkapp and back "
    "down the coast; the party and the drive are the month."
)


def _story(key, title, weight, *, occasion=None, people=(), days, places=(), trip=None):
    return {
        "key": key,
        "episodes": [f"{key}-E1"],
        "title": title,
        "purpose": "",
        "weight": weight,
        "gate": "maybe",
        "seen": {"moments": 1, "pictures": 1, "favourites": 0},
        "people_counts": {},
        "occasion": occasion,
        "people": list(people),
        "days": list(days),
        "places": list(places),
        "trip": trip,
    }


def demo_stories() -> list[dict]:
    first, last = TRIP_DAYS
    return [
        _story("S0004", HOME.title, "glimpse", days=["2025-07-01", "2025-07-10"]),
        _story(
            "S0001",
            BIRTHDAY.title,
            "dominant",
            occasion="birthday",
            people=["Kit"],
            days=["2025-07-05", "2025-07-05"],
            places=["Brussels"],
        ),
        _story("S0003", FOREST.title, "minor", occasion="event", days=["2025-07-06"] * 2),
        _story(
            "S0002-leg1",
            "Through Denmark and Sweden",
            "major",
            occasion="leg",
            days=[first, "2025-07-15"],
            places=["Copenhagen", "Stockholm"],
            trip=TRIP.title,
        ),
        _story(
            "S0002-leg2",
            "Nordkapp and Lofoten",
            "major",
            occasion="leg",
            days=["2025-07-16", "2025-07-24"],
            places=["Nordkapp", "Lofoten"],
            trip=TRIP.title,
        ),
        _story(
            "S0002-leg3",
            "Down the coast",
            "major",
            occasion="leg",
            days=["2025-07-25", last],
            places=["Geiranger"],
            trip=TRIP.title,
        ),
    ]


class ScriptedJudge:
    # WHY: stands in for StructureTextJudge's model call. Like the real judgment bank it answers
    # a prompt it has seen before from its bank, so a reused summary shows up as a cache hit.
    def __init__(self, reply):
        self._reply = reply
        self.bank: dict[str, str] = {}
        self.prompts: list[str] = []

    def ask(self, stage, prompt, max_tokens=0, **_contract):
        self.prompts.append(prompt)
        if prompt not in self.bank:
            self.bank[prompt] = self._reply(prompt)
        return self.bank[prompt]


def _reply(text):
    return lambda _prompt: json.dumps({"summary": text})


# --- Basic: one line, only the stories' names -------------------------------------------------


def test_the_basic_summary_is_the_demo_months_story_names_in_order():
    line = plain_summary(demo_stories(), "en")

    assert line == f"{BIRTHDAY.title}, then {TRIP.title}"


def test_the_basic_summary_names_a_trip_once_for_all_its_legs():
    line = plain_summary(demo_stories(), "en")

    assert line.count(TRIP.title) == 1
    assert "Nordkapp and Lofoten" not in line


def test_the_basic_summary_speaks_the_films_language():
    line = plain_summary(demo_stories(), "fr")

    assert line == f"{BIRTHDAY.title}, puis {TRIP.title}"


def test_a_period_of_small_stories_still_names_its_heaviest():
    stories = [
        _story("S1", "A Sunday in the forest", "minor", days=["2025-07-06"] * 2),
        _story("S2", "Ordinary days", "glimpse", days=["2025-07-01", "2025-07-10"]),
    ]

    assert plain_summary(stories, "en") == "A Sunday in the forest"


def test_weeks_at_home_one_after_another_are_told_once_as_their_span():
    """rc.10, a person's month: four "Days at home" weeks made the whole summary."""
    weeks = [
        ("S1", "2026-09-02", "2026-09-06"),
        ("S2", "2026-09-07", "2026-09-13"),
        ("S3", "2026-09-16", "2026-09-20"),
    ]
    stories = [
        {
            **_story(key, home_name([first, last], [], "fr")[0], "major", days=[first, last]),
            "at_home": True,
        }
        for key, first, last in weeks
    ] + [_story("S4", "Orchardville, Saturday 12 September", "major", days=["2026-09-12"] * 2)]

    assert plain_summary(stories, "fr") == (
        "Jours à la maison, 2–13 septembre, puis Orchardville, Saturday 12 September, "
        "puis Jours à la maison, 16–20 septembre"
    )


def test_days_at_home_years_apart_are_never_one_span():
    """A holiday film over twenty years has a day at home in many of them."""
    stories = [
        {**_story(key, f"Day {key}", "major", days=[day, day]), "at_home": True}
        for key, day in (("S1", "2004-08-15"), ("S2", "2022-08-15"))
    ]

    assert plain_summary(stories, "en") == "Day S1, then Day S2"


def test_a_period_with_no_named_story_has_no_summary():
    assert plain_summary([], "en") == ""


# --- Full: a summary prompt fed the film's own stories ----------------------------------------


def test_the_full_summary_comes_through_the_prompt_and_names_the_birthday_and_the_trip():
    judge = ScriptedJudge(_reply(FULL_REPLY))

    summary = read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")

    assert summary == FULL_REPLY
    assert "birthday" in summary
    assert "road north" in summary


def test_the_full_prompt_is_fed_the_stories_their_days_people_occasions_and_the_trip_legs():
    judge = ScriptedJudge(_reply(FULL_REPLY))

    read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")

    prompt = judge.prompts[0]
    for expected in (
        BIRTHDAY.title,
        TRIP.title,
        "Nordkapp and Lofoten",
        "Kit",
        "birthday",
        "2025-07-05",
        "a month film, 2025-07",
        "which stories mattered",
    ):
        assert expected in prompt
    assert "navigation" not in prompt.lower()


@pytest.mark.parametrize(
    ("locale", "quoted"),
    [("en", "“Kit's birthday”"), ("fr", "« Kit's birthday »"), ("de", "„Kit's birthday“")],
    ids=["en", "fr", "de"],
)
def test_story_names_the_model_quotes_keep_the_summary_in_the_films_quotation_marks(locale, quoted):
    # WHY: asked to name the stories, the model quotes them; a straight quote voided every such
    # summary and the film fell back to its story names (seen on a cluster birthday film).
    judge = ScriptedJudge(_reply('July was "Kit\'s birthday" and the road north.'))

    summary = read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale=locale)

    assert summary == f"July was {quoted} and the road north."


def _home_weeks() -> list[dict]:
    weeks = [("S1", "2026-09-02", "2026-09-06"), ("S2", "2026-09-07", "2026-09-13")]
    return [
        {
            **_story(
                key,
                home_name([first, last], [], "en")[0],
                "major",
                days=[first, last],
                people=["Kit"],
                places=["Jette"],
            ),
            "at_home": True,
        }
        for key, first, last in weeks
    ]


def test_weeks_at_home_one_after_another_reach_the_model_as_one_story():
    # WHY: fed five "Days at home" weeks, the model listed all five, twice over.
    judge = ScriptedJudge(_reply("September was days at home with Kit."))

    read_summary(judge, _home_weeks(), scope="a month film, 2026-09", locale="en")

    cards = [json.loads(line) for line in judge.prompts[0].split("STORIES\n", 1)[1].splitlines()]
    assert [card["name"] for card in cards] == ["Days at home, 2–13 September"]
    assert cards[0]["days"] == ["2026-09-02", "2026-09-13"]
    assert cards[0]["people"] == ["Kit"]


def test_the_model_is_asked_to_name_each_story_once_unquoted():
    judge = ScriptedJudge(_reply(FULL_REPLY))

    read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")

    assert "Name a story at most once" in judge.prompts[0]
    assert "without quotation marks" in judge.prompts[0]


def test_a_summary_naming_one_story_twice_is_refused():
    name = BIRTHDAY.title
    judge = ScriptedJudge(_reply(f"July was {name} and the road north; {name} mattered most."))

    with pytest.raises(ValueError, match="summary"):
        read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")


def test_a_story_named_inside_a_longer_name_is_not_a_repeat():
    stories = [
        _story("S1", "Oslo", "major", days=["2025-07-01"] * 2),
        _story("S2", "Oslo to Tromso", "major", days=["2025-07-02"] * 2),
    ]
    judge = ScriptedJudge(_reply("July began in Oslo, then Oslo to Tromso was the drive."))

    assert read_summary(judge, stories, scope="a month film, 2025-07", locale="en")


def test_an_unpaired_quote_still_voids_the_summary():
    judge = ScriptedJudge(_reply("July was \"Kit's birthday and the road north."))

    with pytest.raises(ValueError, match="summary"):
        read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")


@pytest.mark.parametrize(
    "reply",
    ["not json", json.dumps({"summary": ""}), json.dumps({"summary": "word " * 400})],
)
def test_an_unusable_full_reply_is_refused(reply):
    judge = ScriptedJudge(lambda _prompt: reply)

    with pytest.raises(ValueError, match="summary"):
        read_summary(judge, demo_stories(), scope="a month film, 2025-07", locale="en")


# --- The film's summary, on the planner's path -----------------------------------------------


def _period(stories, thesis=""):
    return PeriodStory(
        thesis=thesis,
        episodes=[],
        connections=[],
        priorities=[],
        uncertainties=[],
        audit={},
        stories=stories,
    )


def _source(product="monthly_highlights", ranges=(("2025-07-01", "2025-07-31"),), people=()):
    return SimpleNamespace(
        case=SimpleNamespace(
            product=product,
            ranges=tuple(SimpleNamespace(start=start, end=end) for start, end in ranges),
            people=people,
        ),
        config=SimpleNamespace(
            title_screens=SimpleNamespace(locale="en"), editorial=SimpleNamespace()
        ),
    )


def _carriers(stories):
    return [{"asset_id": f"a-{s['key']}", "story_episode": s["key"]} for s in stories]


def _summarise(source, *, thin, judge=None, story=None):
    stories = demo_stories()
    story = story or _period(stories)
    records: dict = {}
    summarise_the_film(
        source,
        SimpleNamespace(thin=object() if thin else None, judge=judge),
        SimpleNamespace(story=story),
        _carriers(stories),
        record=records.__setitem__,
    )
    return story, records


def test_a_basic_film_states_the_story_names_as_its_summary():
    story, records = _summarise(_source(), thin=False)

    assert story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"
    assert records["film-summary"]["tier"] == "basic"


def test_a_full_film_states_the_models_summary():
    story, records = _summarise(_source(), thin=True, judge=ScriptedJudge(_reply(FULL_REPLY)))

    assert story.thesis == FULL_REPLY
    assert records["film-summary"]["tier"] == "full"


def test_a_full_film_whose_summary_failed_says_its_story_names():
    story, records = _summarise(
        _source(), thin=True, judge=ScriptedJudge(lambda _prompt: "not json")
    )

    assert story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"
    assert records["film-summary"]["tier"] == "basic"
    assert records["film-summary"]["fallback"]


def test_a_synthesis_thesis_is_kept():
    story, _records = _summarise(_source(), thin=False, story=_period(demo_stories(), "Kept."))

    assert story.thesis == "Kept."


def test_only_the_stories_the_film_shows_are_summarised():
    stories = demo_stories()
    story = _period(stories)
    summarise_the_film(
        _source(),
        SimpleNamespace(thin=None, judge=None),
        SimpleNamespace(story=story),
        _carriers([s for s in stories if s["key"] != "S0001"]),
        record=lambda *_args: None,
    )

    assert story.thesis == TRIP.title


@pytest.mark.parametrize(
    "other",
    [
        _source("person_spotlight", (("2019-03-02", "2025-07-31"),), ("Kit",)),
        _source("season", (("2025-06-01", "2025-08-31"),)),
        _source("year_in_review", (("2025-01-01", "2025-12-31"),)),
    ],
    ids=["person", "season", "year"],
)
def test_a_film_of_another_scope_never_reuses_the_months_summary(other):
    judge = ScriptedJudge(lambda _prompt: json.dumps({"summary": f"Reply {len(judge.bank)}."}))
    month, _ = _summarise(_source(), thin=True, judge=judge)

    film, _ = _summarise(other, thin=True, judge=judge)

    assert judge.prompts[0] != judge.prompts[1]
    assert film.thesis != month.thesis


def test_the_same_film_asked_again_reads_its_own_summary_back():
    judge = ScriptedJudge(lambda _prompt: json.dumps({"summary": f"Reply {len(judge.bank)}."}))
    first, _ = _summarise(_source(), thin=True, judge=judge)

    again, _ = _summarise(_source(), thin=True, judge=judge)

    assert again.thesis == first.thesis


# --- The navigation note is never the summary ------------------------------------------------


class Thin:
    """# WHY: stands in for ThinPolish, whose model calls have their own tests; only the account matters here."""

    def catalogue_of(self, story, moment_assets, *, drafted):
        return SimpleNamespace(thesis=NAVIGATION_NOTE)

    def polish(self, carriers, **_options):
        return carriers


def test_the_period_accounts_navigation_note_never_becomes_the_film_summary():
    story = _period(demo_stories())
    source = SimpleNamespace(
        **vars(_source()),
        audience="family",
        owner_required_asset_ids=(),
        intent=SimpleNamespace(subject="", voice_per_partition=False, pool_is_subject=False),
        people=None,
        render_timing=None,
        audience_annotations={},
        assets={},
    )
    ports = SimpleNamespace(thin=Thin(), judge=ScriptedJudge(_reply(FULL_REPLY)))
    selection = SimpleNamespace(story=story, lines={}, episodes=[])
    carriers = _carriers(demo_stories())

    polish_the_draft(
        source,
        ports,
        SimpleNamespace(units={}),
        SimpleNamespace(),
        selection,
        SimpleNamespace(moment_assets={}),
        None,
        carriers,
        SimpleNamespace(final_content_cap=60.0, cut_carriers=[]),
        contract="",
        record=lambda *_args: None,
        gates=None,
    )
    summarise_the_film(source, ports, selection, carriers, record=lambda *_args: None)

    assert story.thesis == FULL_REPLY
    assert NAVIGATION_NOTE not in story.thesis


# --- A refined film is summarised by the model, not left with its draft's line --------------


def test_a_refined_film_asks_the_model_for_its_summary_not_the_drafts_basic_line():
    """On Full, the rules draft is summarised first (Basic, no model), then refined. The
    refinement took the draft's selection over with that line on it, so the model summary
    never ran and a Full film showed the Basic line (rc.10, a birthday film: 33 model
    calls, no summary call)."""
    from immich_memories.analysis.editorial_story_planner import StorySelection
    from immich_memories.analysis.editorial_structure_planner import _story_selection

    stories = demo_stories()
    drafted = StorySelection(
        carriers=_carriers(stories),
        story=_period(stories),
        episodes=[],
        alternatives_of={},
        slots=len(stories),
        calls={},
        lines={},
    )
    summarise_the_film(
        _source(),
        SimpleNamespace(thin=None, judge=None),
        drafted,
        drafted.carriers,
        record=lambda *_args: None,
    )
    assert drafted.story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"

    refined = _story_selection(
        SimpleNamespace(annotations={}),
        # WHY: the refinement's draft port; only the draft it hands over is read here.
        SimpleNamespace(draft=SimpleNamespace(carriers=drafted.carriers, selection=drafted)),
        wall=None,
        material=SimpleNamespace(builder=SimpleNamespace(refresh_clip_facts=dict)),
        pool=None,
        gate=None,
        contract="",
        tier={},
        marker="",
        record=lambda *_args: None,
        partition_limit=None,
        banked=None,
    )
    records: dict = {}
    summarise_the_film(
        _source(),
        SimpleNamespace(thin=object(), judge=ScriptedJudge(_reply(FULL_REPLY))),
        refined,
        refined.carriers,
        record=records.__setitem__,
    )

    assert refined.story.thesis == FULL_REPLY
    assert records["film-summary"]["tier"] == "full"
