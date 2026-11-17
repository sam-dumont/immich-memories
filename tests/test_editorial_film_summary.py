"""A film says what its period was about, from its own shots, on every tier (#2488, #2594).

The stories are stand-ins in the record shape the rules reader writes (#2486 contract): the
demo month's answer key in `tests/e2e/fake_library.py`, with its trip split into legs. With a
model the summary is two small questions: the period's thesis, then one sentence from that
thesis and a line code counts from the shots.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from immich_memories.analysis.polish.period_thesis import FilmShots
from immich_memories.analysis.stories.names import home_name
from immich_memories.analysis.stories.period_account import PeriodStory
from immich_memories.analysis.structure.film_summary import (
    SUMMARY_VERSION,
    plain_summary,
    read_summary,
    shows_line,
    summarise_the_film,
)
from immich_memories.analysis.structure.thin_step import polish_the_draft
from immich_memories.api.film_label import film_label
from immich_memories.store.episode_readings import (
    BankedEpisodeReading,
    EpisodeReadingIdentity,
    EpisodeRepresentative,
)
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
THESIS = "Kit's birthday at home, then twenty days on the road north to Nordkapp with Robin."
FULL_REPLY = "Kit blows out the candles at home, then drives north to Nordkapp with Robin."


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
    # a prompt it has seen before from its bank, so a reused answer shows up as a cache hit.
    def __init__(self, summary, thesis=lambda _prompt: json.dumps({"thesis": THESIS})):
        self._replies = {"period-thesis": thesis, "film-summary": summary}
        self.bank: dict[str, str] = {}
        self.prompts: list[str] = []
        self.stages: list[str] = []

    def ask(self, stage, prompt, max_tokens=0, **_contract):
        self.stages.append(stage)
        self.prompts.append(prompt)
        if prompt not in self.bank:
            self.bank[prompt] = self._replies[stage](prompt)
        return self.bank[prompt]


def _reply(text):
    return lambda _prompt: json.dumps({"summary": text})


def _reading(asset_ids, what):
    return BankedEpisodeReading(
        identity=EpisodeReadingIdentity(f"g-{asset_ids[0]}", "producer", "evidence"),
        full_asset_ids=tuple(asset_ids),
        what_happened=what,
        representatives=(EpisodeRepresentative(asset_ids[0], "the moment"),),
        cull_decisions=(),
    )


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


# --- Full: the thesis, then one sentence from it and the counted shots -----------------------

# Twelve shots of the demo month: the birthday's four, the trip's first leg's five, the
# forest's two and one day at home. Every name is made up.
SHOTS = [
    *(
        {
            "asset_id": f"b{n}",
            "story_episode": "S0001",
            "line": f"2025-07-05 | cake {n} | with Kit (son); Robin | activity=eating-drinking",
        }
        for n in range(1, 5)
    ),
    *(
        {
            "asset_id": f"t{n}",
            "story_episode": "S0002-leg1",
            "line": f"2025-07-13 | road {n} | with Robin | activity=sightseeing",
        }
        for n in range(1, 6)
    ),
    *(
        {"asset_id": f"f{n}", "story_episode": "S0003", "line": f"2025-07-06 | trees {n}"}
        for n in range(1, 3)
    ),
    {"asset_id": "h1", "story_episode": "S0004", "line": "2025-07-02 | a sofa"},
]
READINGS = (
    _reading(["b1", "b2", "b3", "b4"], "Kit blows out the candles on his cake."),
    _reading(["t1", "t2", "t3", "t4", "t5"], "Robin drives north past the fjords."),
    _reading(["f1", "f2"], "A walk under tall trees."),
)


def _shots(readings=READINGS):
    return FilmShots(carriers=SHOTS, stories=demo_stories(), readings=readings)


def test_the_counted_line_names_the_three_largest_groups_of_shots_then_what_people_do():
    assert shows_line(_shots()) == (
        "5 of 12: Robin drives north past the fjords; 4 of 12: Kit blows out the candles on his "
        "cake; 2 of 12: A walk under tall trees; 1 other shots. Doing: sightseeing (5), "
        "a meal (4)"
    )


def test_a_group_nothing_read_is_counted_with_the_other_shots():
    assert shows_line(_shots(READINGS[:1])) == (
        "4 of 12: Kit blows out the candles on his cake; 8 other shots. "
        "Doing: sightseeing (5), a meal (4)"
    )


def test_the_summary_prompt_is_the_thesis_and_the_counted_shots():
    judge = ScriptedJudge(_reply(FULL_REPLY))

    summary = read_summary(
        judge, _shots(), thesis=THESIS, scope="a month film, 2025-07", locale="fr"
    )

    assert summary == FULL_REPLY
    assert judge.stages == ["film-summary"]
    assert judge.prompts[0] == (
        f"What does this film show? {SUMMARY_VERSION}\n"
        "THE FILM: a month film, 2025-07.\n"
        f"ITS SHOTS, counted: {shows_line(_shots())}\n"
        f"THE PERIOD: {THESIS}\n"
        "\n"
        "One sentence of at most 25 words, in French: who it was with and what they did, the\n"
        "shots first. Only these facts; no ids.\n"
        'JSON only: {"summary":"..."}'
    )


def test_the_occasion_is_its_own_line_and_never_added_to_the_answer():
    judge = ScriptedJudge(_reply("Kit and Robin visit a castle."))

    summary = read_summary(
        judge, _shots(), thesis=THESIS, scope="a holiday film", locale="en", occasion="Assumption"
    )

    assert "THE FILM: a holiday film.\nTHE OCCASION: Assumption.\nITS SHOTS" in judge.prompts[0]
    assert summary == "Kit and Robin visit a castle."


def test_an_unpaired_quote_still_voids_the_summary():
    judge = ScriptedJudge(_reply("July was \"Kit's birthday and the road north."))

    with pytest.raises(ValueError, match="summary"):
        read_summary(judge, _shots(), thesis=THESIS, scope="a month film", locale="en")


@pytest.mark.parametrize(
    "reply",
    ["not json", json.dumps({"summary": ""}), json.dumps({"summary": "word " * 400})],
)
def test_an_unusable_full_reply_is_refused(reply):
    judge = ScriptedJudge(lambda _prompt: reply)

    with pytest.raises(ValueError, match="summary"):
        read_summary(judge, _shots(), thesis=THESIS, scope="a month film", locale="en")


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
        # Model-written text turned on (`title_screens.llm_titles`), as the tests below need.
        config=SimpleNamespace(
            title_screens=SimpleNamespace(locale="en", llm_titles=True),
            editorial=SimpleNamespace(),
        ),
    )


def _carriers(stories):
    return [{"asset_id": f"a-{s['key']}", "story_episode": s["key"]} for s in stories]


class Thin:
    """# WHY: stands in for ThinPolish, whose model calls have their own tests: the readings the
    run read, and the account its polish read when the draft's thesis was not given."""

    def __init__(self, readings=()) -> None:
        self._readings = tuple(readings)

    def readings(self):
        return self._readings

    def catalogue_of(self, story, moment_assets, *, drafted, thesis_of=lambda: ""):
        return SimpleNamespace(thesis=thesis_of() or NAVIGATION_NOTE)

    def polish(self, carriers, **_options):
        return carriers


def _summarise(source, *, thin, judge=None, story=None, carriers=None):
    stories = demo_stories()
    story = story or _period(stories)
    records: dict = {}
    summarise_the_film(
        source,
        SimpleNamespace(thin=Thin(READINGS) if thin else None, judge=judge),
        SimpleNamespace(story=story, lines={}),
        carriers if carriers is not None else _carriers(stories),
        record=records.__setitem__,
    )
    return story, records


@pytest.mark.parametrize("thin", [True, False], ids=["full", "basic"])
def test_a_film_has_no_summary_until_model_text_is_turned_on(thin):
    # WHY: model-written summaries are experimental (#2594), and the story-name line reads as
    # a list of places and dates: with the setting off a film has no summary at all.
    source = _source()
    source.config.title_screens.llm_titles = False
    judge = ScriptedJudge(_reply(FULL_REPLY))

    story, records = _summarise(source, thin=thin, judge=judge)

    assert story.thesis == ""
    assert judge.prompts == []
    assert records["film-summary"]["tier"] == "off"


def test_a_synthesis_thesis_is_not_kept_with_model_text_off():
    source = _source()
    source.config.title_screens.llm_titles = False

    story, _ = _summarise(source, thin=True, story=_period(demo_stories(), thesis="A model's line"))

    assert story.thesis == ""


def test_a_basic_film_states_the_story_names_as_its_summary():
    story, records = _summarise(_source(), thin=False)

    assert story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"
    assert records["film-summary"]["tier"] == "basic"


def test_a_full_film_asks_the_thesis_then_the_summary_and_describes_itself_with_the_answer():
    judge = ScriptedJudge(lambda _prompt: f'```json\n{{"summary": "{FULL_REPLY}"}}\n```')

    story, records = _summarise(_source(), thin=True, judge=judge, carriers=SHOTS)

    assert judge.stages == ["period-thesis", "film-summary"]
    assert "1. Kit's birthday (dominant; 4 of 12 shots)" in judge.prompts[0]
    assert f"THE PERIOD: {THESIS}\n" in judge.prompts[1]
    assert "ITS SHOTS, counted: 5 of 12: Robin drives north past the fjords;" in judge.prompts[1]
    assert story.thesis == FULL_REPLY
    assert records["film-summary"] | {"stories": []} == {
        "version": SUMMARY_VERSION,
        "tier": "full",
        "scope": "a monthly_highlights film, 2025-07-01 to 2025-07-31",
        "thesis": THESIS,
        "summary": FULL_REPLY,
        "stories": [],
    }
    label = film_label(
        title="July 2025",
        summary=story.thesis,
        type_label=None,
        date_start=None,
        date_end=None,
        episodes=(),
    )
    assert label.description is not None
    assert label.description.endswith(FULL_REPLY)


def test_a_full_film_whose_summary_failed_says_its_story_names():
    story, records = _summarise(
        _source(), thin=True, judge=ScriptedJudge(lambda _prompt: "not json")
    )

    assert story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"
    assert records["film-summary"]["tier"] == "basic"
    assert records["film-summary"]["fallback"]


def test_a_full_film_whose_thesis_failed_asks_no_summary_and_says_its_story_names():
    judge = ScriptedJudge(_reply(FULL_REPLY), thesis=lambda _prompt: "{}")

    story, records = _summarise(_source(), thin=True, judge=judge)

    assert judge.stages == ["period-thesis"]
    assert story.thesis == f"{BIRTHDAY.title}, then {TRIP.title}"
    assert "thesis" in records["film-summary"]["fallback"]


def test_a_synthesis_thesis_is_kept():
    story, _records = _summarise(_source(), thin=False, story=_period(demo_stories(), "Kept."))

    assert story.thesis == "Kept."


def test_only_the_stories_the_film_shows_are_summarised():
    stories = demo_stories()
    story = _period(stories)
    summarise_the_film(
        _source(),
        SimpleNamespace(thin=None, judge=None),
        SimpleNamespace(story=story, lines={}),
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

    assert judge.prompts[0] != judge.prompts[2]
    assert judge.prompts[1] != judge.prompts[3]
    assert film.thesis != month.thesis


def test_the_same_film_asked_again_reads_its_own_summary_back():
    judge = ScriptedJudge(lambda _prompt: json.dumps({"summary": f"Reply {len(judge.bank)}."}))
    first, _ = _summarise(_source(), thin=True, judge=judge)

    again, _ = _summarise(_source(), thin=True, judge=judge)

    assert again.thesis == first.thesis


def test_both_prompts_carry_their_version_so_answers_banked_under_older_ones_are_not_reused():
    judge = ScriptedJudge(_reply(FULL_REPLY))

    _summarise(_source(), thin=True, judge=judge)

    assert judge.prompts[0].splitlines()[0].endswith(" period-thesis-v1")
    assert judge.prompts[1].splitlines()[0].endswith(" film-summary-v4")
    assert not any("film-summary-v3" in prompt for prompt in judge.prompts)


# --- The navigation note is never the summary, and the draft's thesis is the vote's ----------


def _polish_source():
    return SimpleNamespace(
        **vars(_source()),
        audience="family",
        owner_required_asset_ids=(),
        intent=SimpleNamespace(subject="", voice_per_partition=False, pool_is_subject=False),
        people=None,
        render_timing=None,
        audience_annotations={},
        assets={},
    )


def _polish(source, ports, selection, carriers, records):
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
        record=records.__setitem__,
        gates=None,
    )


def test_the_period_accounts_navigation_note_never_becomes_the_film_summary():
    story = _period(demo_stories())
    source = _polish_source()
    ports = SimpleNamespace(thin=Thin(READINGS), judge=ScriptedJudge(_reply(FULL_REPLY)))
    selection = SimpleNamespace(story=story, lines={}, episodes=[])

    _polish(source, ports, selection, SHOTS, {})
    summarise_the_film(source, ports, selection, SHOTS, record=lambda *_args: None)

    assert story.thesis == FULL_REPLY
    assert not any(NAVIGATION_NOTE in prompt for prompt in ports.judge.prompts)


def test_the_draft_is_judged_against_its_own_thesis_asked_from_its_shots():
    seen = {}

    class Polish(Thin):
        def polish(self, carriers, *, catalogue, **_options):
            seen["thesis"] = catalogue.thesis
            return carriers

    ports = SimpleNamespace(thin=Polish(READINGS), judge=ScriptedJudge(_reply(FULL_REPLY)))
    records: dict = {}

    _polish(
        _polish_source(),
        ports,
        SimpleNamespace(story=_period(demo_stories()), lines={}, episodes=[]),
        SHOTS,
        records,
    )

    assert seen["thesis"] == THESIS
    assert ports.judge.stages == ["period-thesis"]
    assert records["period-thesis"] == {"version": "period-thesis-v1", "thesis": THESIS}


def test_a_draft_whose_thesis_failed_is_judged_against_the_account():
    seen = {}

    class Polish(Thin):
        def polish(self, carriers, *, catalogue, **_options):
            seen["thesis"] = catalogue.thesis
            return carriers

    judge = ScriptedJudge(_reply(FULL_REPLY), thesis=lambda _prompt: "not json")
    records: dict = {}

    _polish(
        _polish_source(),
        SimpleNamespace(thin=Polish(), judge=judge),
        SimpleNamespace(story=_period(demo_stories()), lines={}, episodes=[]),
        SHOTS,
        records,
    )

    assert seen["thesis"] == NAVIGATION_NOTE
    assert records["period-thesis"]["thesis"] == ""
    assert records["period-thesis"]["fallback"]


# --- A refined film is summarised by the model, not left with its draft's line --------------


def test_a_refined_film_asks_the_model_for_its_summary_not_the_drafts_basic_line():
    """On Full, the rules draft is summarised first (Basic, no model), then refined. The
    refinement took the draft's selection over with that line on it, so the model summary
    never ran and a Full film showed the Basic line (rc.10, a birthday film: 33 model
    calls, no summary call)."""
    from immich_memories.analysis.selection.story_planner import StorySelection
    from immich_memories.analysis.structure.planner import _story_selection

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
        SimpleNamespace(thin=Thin(), judge=ScriptedJudge(_reply(FULL_REPLY))),
        refined,
        refined.carriers,
        record=records.__setitem__,
    )

    assert refined.story.thesis == FULL_REPLY
    assert records["film-summary"]["tier"] == "full"


# --- The language the summary was written in (#2535) ------------------------------------------


def test_a_summary_records_the_language_it_was_written_in():
    source = _source()
    source.config.title_screens.locale = "fr"

    story, _records = _summarise(source, thin=False)

    assert story.thesis_locale == "fr"


def test_a_kept_synthesis_thesis_claims_no_language():
    story, _records = _summarise(_source(), thin=False, story=_period(demo_stories(), "Kept."))

    assert story.thesis_locale == ""


def test_the_plan_keeps_the_summarys_language_for_a_later_render():
    from immich_memories.analysis.selection.story_planner import StorySelection

    stories = demo_stories()
    selection = StorySelection(
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
        selection,
        _carriers(stories),
        record=lambda *_args: None,
    )

    assert selection.record()["thesis_locale"] == "en"


def test_a_holiday_film_is_summarised_from_its_holiday_and_the_years_it_shows():
    stories = [
        _story("S1", "Les Alpes", "major", days=["2004-08-15"] * 2),
        _story("S2", "Retour", "major", days=["2026-08-15"] * 2),
    ]
    source = _source(product="holiday")
    source.case.occasion = "Assumption"
    judge = ScriptedJudge(_reply("Kit and Pat visit a castle."))
    story = _period(stories)

    summarise_the_film(
        source,
        SimpleNamespace(thin=Thin(), judge=judge),
        SimpleNamespace(story=story, lines={}),
        _carriers(stories),
        record={}.__setitem__,
    )

    assert all("THE OCCASION: Assumption, 2004–2026.\n" in prompt for prompt in judge.prompts)
    assert story.thesis == "Kit and Pat visit a castle."
