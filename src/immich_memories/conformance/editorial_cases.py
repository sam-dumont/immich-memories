"""Synthetic editorial choices with measurable consequences for the proposed film."""

from datetime import date
from functools import partial

from immich_memories.analysis.editorial_block_votes import judge_worthiness
from immich_memories.analysis.editorial_story_reading import (
    PeriodStory,
    StoryEpisode,
    read_period_story,
)
from immich_memories.analysis.editorial_story_replies import WEIGHTS
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_threads import fold_threads
from immich_memories.analysis.editorial_story_vote import pick_story_moments
from immich_memories.analysis.editorial_story_weighing import _weigh_stories
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_judge
from immich_memories.conformance.runtime import Case


def worthiness(llm: LLMConfig) -> str:
    rows = {
        "race": "Cyclists cross the finish line of a race; the winner receives a trophy.",
        "quiet": "The cat sleeps on the sofa on an ordinary afternoon.",
        "meal": "An ordinary sandwich lunch at home.",
        "desk": "The same desk and keyboard used every workday.",
    }
    with scratch_judge(llm) as judge:
        tiers, _, rounds = judge_worthiness(
            judge,
            happenings=list(rows),
            label_of={key: f"H{n}" for n, key in enumerate(rows, 1)},
            text_of=rows.__getitem__,
            near_home=lambda _: None,
            contract="A monthly highlights film.",
            contract_key="synthetic",
            criterion="Choose remarkable occasions worth telling other people about, not routine daily scenes.",
            marker="conformance",
            period_label="June 2030",
        )
    assert tiers["race"] == 0 and tiers["quiet"] == 2, "race did not outrank the ordinary afternoon"
    assert rounds, "worthiness did not record its comparisons"
    return "race is remarkable in both orders; ordinary afternoon is background"


def period_story(llm: LLMConfig) -> str:
    evidence = [
        {
            "episode": f"E{n}",
            "episode_evidence_key": f"evidence-{n}",
            "capture_group": f"M{n}",
            "moments": [f"M{n}"],
            "taken": f"2030-06-{n:02d}T12:00:00",
            "last_taken": f"2030-06-{n:02d}T12:30:00",
            "places": "",
            "known_people_in_group": "",
            "person_links": "",
            "captures": 4,
            "favourites": 0,
            "video": 0,
            "live": 0,
            "what_happened": text,
            "observations": [text],
            "named_observations": 1,
        }
        for n, text in enumerate(
            (
                "Cyclists cross the finish line at a cycling race and receive a trophy.",
                "A cat sleeps on a sofa at home on an ordinary afternoon.",
            ),
            1,
        )
    ]
    with scratch_judge(llm) as judge:
        answer = read_period_story(
            judge, evidence=evidence, contract="A monthly highlights film of June 2030.", prior={}
        )
    assert {moment for episode in answer.episodes for moment in episode.moments} == {"M1", "M2"}, (
        "period reader lost an episode"
    )
    assert "race" in answer.thesis.lower(), "period thesis lost the race"
    race = [story for story in answer.stories if "race" in story["title"].lower()]
    routine = [story for story in answer.stories if story not in race]
    assert (
        race
        and routine
        and WEIGHTS.index(race[0]["weight"])
        < min(WEIGHTS.index(story["weight"]) for story in routine)
    ), "race did not outrank the routine home scene"
    assert all(not page["unplaced"] for page in answer.audit["pages"]), (
        "unread rows silently fell back"
    )
    return "reads both days, groups their stories and ranks the race above the routine scene"


def central_story(llm: LLMConfig) -> str:
    stories = [
        {
            "key": f"K{n:02d}",
            "episodes": [f"S{n}"],
            "title": title,
            "purpose": purpose,
            "weight": "",
        }
        for n, (title, purpose) in enumerate(
            (
                ("Cycling race", "The owner races across the finish line and receives a trophy."),
                ("Quiet afternoon", "A cat sleeps at home."),
                ("Ordinary lunch", "A sandwich at home."),
            ),
            1,
        )
    ]
    records: list[dict] = []
    with scratch_judge(llm) as judge:
        answer = _weigh_stories(
            judge,
            stories,
            thesis="The owner's cycling race is the central occasion.",
            hints={},
            contract="A monthly highlights film.",
            record=records.append,
            day_of=lambda key: f"2030-06-{int(key[1:]):02d}",
            candidates=[s["key"] for s in stories],
        )
    context = next(row for row in records if row["stage"] == "story-weighing-candidate-context")
    assert context["confirmed"] == ["K01"] and not context["fallback"], (
        "central story was not confirmed by both votes"
    )
    assert next(s for s in answer if s["key"] == "K01")["weight"] == "dominant", (
        "confirmed race did not become dominant"
    )
    return "both candidate comparisons confirm the race as the central story"


def moment_selection(llm: LLMConfig) -> str:
    choices = [
        DepictedChoice(
            "finish",
            "race",
            "2030-06-01T12:00:00",
            "The owner crosses the finish line of a cycling race, cheered by family.",
            "finish-photo",
        ),
        DepictedChoice(
            "empty",
            "race",
            "2030-06-01T12:15:00",
            "An empty bicycle rack with no riders or people.",
            "empty-photo",
        ),
    ]
    records: list[dict] = []
    with scratch_judge(llm) as judge:
        answer = pick_story_moments(
            judge,
            story={"key": "race", "title": "The owner's cycling race"},
            choices=choices,
            count=1,
            starred=lambda _: False,
            contract="Choose a personal memory of the race.",
            record=lambda _stage, row: records.append(dict(row)),
        )
    assert records and all(
        not vote.get("review_stage") for row in records for vote in row["vote_records"]
    ), "moment selection used a fallback or repaired its grant by trimming"
    assert [choice.key for choice in answer] == ["finish"], (
        "pick preferred empty scenery to the owner's participation"
    )
    return "selects the owner at the finish line instead of an empty rack"


def recurring_activity(llm: LLMConfig) -> str:
    episodes = [
        StoryEpisode(f"S{n}", title, title, "", "supporting", "", moments=[f"M{n}"])
        for n, title in enumerate(("Swimming lesson", "Swimming lesson", "Ordinary home day"), 1)
    ]
    stories = [
        {
            "key": f"K{n:02d}",
            "episodes": [episode.key],
            "title": episode.title,
            "weight": "minor",
            "purpose": "A repeated weekly activity",
        }
        for n, episode in enumerate(episodes, 1)
    ]
    hints = {
        f"S{n}": {"day": f"2030-06-{day:02d}", "place": place}
        for n, day, place in ((1, 1, "Swimming pool"), (2, 8, "Swimming pool"), (3, 9, "Home"))
    }
    story = PeriodStory("Weekly swimming lessons", episodes, [], [], [], {"hints": hints}, stories)
    with scratch_judge(llm) as judge:
        asked = fold_threads(
            judge,
            story,
            contract="A year-in-review film.",
            span=(date(2030, 1, 1), date(2030, 12, 31)),
            lines=(),
            record=lambda *_: None,
            near_home=lambda moments: "M3" in moments,
        )
    threads = [row for row in story.stories if row.get("thread")]
    assert asked and len(threads) == 1 and set(threads[0]["episodes"]) == {"S1", "S2"}, (
        "swimming lessons did not become one recurring activity"
    )
    return "folds both swimming lessons while keeping the home day separate"


def editorial_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "recurring activity",
            partial(recurring_activity, llm),
            frozenset({"analysis.editorial_story_threads:_ask"}),
        ),
        Case(
            "story moment selection",
            partial(moment_selection, llm),
            frozenset(
                {
                    "analysis.editorial_story_vote:_vote_both_orders",
                    "analysis.editorial_story_pick_contract:ask_moment_pick",
                }
            ),
        ),
        Case(
            "central story confirmation",
            partial(central_story, llm),
            frozenset({"analysis.editorial_story_weighing:_page_context_candidates"}),
        ),
        Case(
            "period story",
            partial(period_story, llm),
            frozenset(
                {
                    "analysis.editorial_story_reading:_read_month_page",
                    "analysis.editorial_page_recovery:read_page_answer",
                    "analysis.editorial_story_grouping:_group_stories",
                    "analysis.editorial_story_weighing:_ask_both_orders",
                    "analysis.editorial_story_weight_contract:ask_complete_weights",
                }
            ),
        ),
        Case(
            "memory worthiness",
            partial(worthiness, llm),
            frozenset(
                {
                    "analysis.editorial_block_votes:_ask_orders",
                    "analysis.editorial_structure_io:StructureTextJudge.ask",
                }
            ),
        ),
    )
