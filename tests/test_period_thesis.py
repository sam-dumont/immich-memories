"""A period's thesis: what the biggest occasions were and who was there, read from the cut (#2594).

The period's account is a navigation note over the whole period, in English. The thesis is the
film's own: its four heaviest stories with their share of the shots and what the readings of
their episodes say, the people on the most pictures, two short sentences in the film's language.
Every name and place below is made up.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from immich_memories.analysis.polish.layer import ThinPolish
from immich_memories.analysis.polish.period_thesis import (
    THESIS_VERSION,
    FilmShots,
    read_thesis,
    thesis_prompt,
)
from immich_memories.analysis.selection.picture_admission import PictureAdmission
from immich_memories.config.models.llm import LLMConfig
from immich_memories.db import open_store
from immich_memories.store.episode_readings import (
    BankedEpisodeReading,
    EpisodeReadingIdentity,
    EpisodeRepresentative,
)


def reading(group: str, members: list[str], what: str) -> BankedEpisodeReading:
    return BankedEpisodeReading(
        identity=EpisodeReadingIdentity(group, "producer", "evidence"),
        full_asset_ids=tuple(members),
        what_happened=what,
        representatives=(EpisodeRepresentative(members[0], "the moment"),),
        cull_decisions=(),
    )


def story(key, title, weight, day, **more):
    return {"key": key, "title": title, "weight": weight, "days": [day, day], **more}


STORIES = [
    story("S5", "Ordinary days", "glimpse", "2030-06-01"),
    story("S3", "posing at Hill Town / working at Brookside", "minor", "2030-06-02"),
    story("S1", "Robin's birthday", "dominant", "2030-06-04"),
    story("S2", "Through the hills", "major", "2030-06-10", trip="The road to the lakes"),
    story("S4", "A walk in the woods", "minor", "2030-06-20"),
]

KIT = "Kit (son; inner circle)"
ROBIN = "Robin (daughter)"
LINES = {
    "b1": f"2030-06-04T10:00 | a cake with candles | with {KIT}; {ROBIN}; Avery; Jules; Noor",
    "b2": f"2030-06-04T10:05 | presents on a table | with {KIT}; {ROBIN}; Avery; Jules",
    "b3": f"2030-06-04T11:00 | a garden | with {KIT}; {ROBIN}; Avery",
    "b4": f"2030-06-04T12:00 | a swing | with {KIT}; {ROBIN}",
    "t1": f"2030-06-10T09:00 | a lake | with {KIT}",
    "t2": f"2030-06-11T09:00 | a boat | with {KIT}",
    "t3": "2030-06-12T09:00 | a road",
    "h1": "2030-06-02T15:00 | a hill",
    "h2": "2030-06-02T15:30 | a blanket",
    "w1": "2030-06-20T10:00 | trees",
    "w2": "2030-06-20T10:30 | a dog",
    "o1": "2030-06-01T08:00 | a kitchen",
}
CARRIERS = [
    {"asset_id": asset, "story_episode": key, "line": LINES[asset]}
    for key, assets in (
        ("S5", ["o1"]),
        ("S3", ["h1", "h2"]),
        ("S1", ["b1", "b2", "b3", "b4"]),
        ("S2", ["t1", "t2", "t3"]),
        ("S4", ["w1", "w2"]),
    )
    for asset in assets
]
READINGS = (
    reading("E1", ["b1", "b2"], "Robin blows out the candles on a cake with Kit."),
    reading("E2", ["b3"], "Kit and Robin open presents in the garden."),
    reading("E3", ["b4"], "Robin on a swing."),
    reading("E4", ["t1", "t2", "t3"], "Kit swims in a lake, then a boat trip."),
    reading("E5", ["h1", "h2"], "A picnic on a hill."),
    reading("E6", ["w1", "w2"], "A dog walk in the woods."),
    reading("E7", ["o1"], "Breakfast at home."),
)


def shots(carriers=CARRIERS, readings=READINGS) -> FilmShots:
    return FilmShots(carriers=carriers, stories=STORIES, readings=readings, line_of=LINES.get)


EXPECTED = """Say what this period of a family's life was about, for the film made of it. period-thesis-v1
THE FILM: a monthly_highlights film, 2030-06-01 to 2030-06-30.
PEOPLE, those on the most pictures: Kit (son); Robin (daughter); Avery; Jules; and 1 others
THE BIGGEST OCCASIONS, largest first, each with what its pictures show:
1. Robin's birthday (dominant; 4 of 12 shots)
   - Robin blows out the candles on a cake with Kit.
   - Kit and Robin open presents in the garden.
2. The road to the lakes (major; 3 of 12 shots)
   - Kit swims in a lake, then a boat trip.
3. (minor; 2 of 12 shots)
   - A picnic on a hill.
4. A walk in the woods (minor; 2 of 12 shots)
   - A dog walk in the woods.

Write at most 2 short sentences in English. The first: what the biggest occasion was (name it:
a birthday, Christmas, a trip, a walk...), who was there by first name, and where. The second, only if the period held more: the next one or two. Say what they did, never "spent time together". Use only these facts. No ids.
JSON only: {"thesis":"..."}"""


def test_the_thesis_prompt_reads_the_four_heaviest_stories_and_the_people_on_most_pictures():
    prompt = thesis_prompt(
        shots(),
        scope="a monthly_highlights film, 2030-06-01 to 2030-06-30",
        occasion="",
        language="English",
    )

    assert prompt == EXPECTED


def test_a_story_reads_at_most_two_episodes_the_ones_holding_most_of_its_shots():
    prompt = thesis_prompt(shots(), scope="a film", occasion="", language="English")

    assert "Robin on a swing." not in prompt


def test_the_glimpse_past_the_fourth_story_is_left_out():
    prompt = thesis_prompt(shots(), scope="a film", occasion="", language="English")

    assert "Breakfast at home." not in prompt
    assert "Ordinary days" not in prompt


def test_a_story_the_rules_named_with_its_place_list_keeps_its_readings_not_its_title():
    prompt = thesis_prompt(shots(), scope="a film", occasion="", language="English")

    assert "posing at Hill Town" not in prompt
    assert "3. (minor; 2 of 12 shots)\n   - A picnic on a hill." in prompt


def test_the_occasion_is_its_own_line_when_the_film_has_one():
    prompt = thesis_prompt(
        shots(), scope="a birthday film", occasion="Robin's birthday", language="French"
    )

    assert "THE FILM: a birthday film.\nTHE OCCASION: Robin's birthday.\nPEOPLE," in prompt
    assert "Write at most 2 short sentences in French." in prompt


def test_a_cut_nobody_is_named_on_and_nothing_was_read_still_asks_from_its_stories():
    bare = [dict(c, line="2030-06-04T10:00 | a cake") for c in CARRIERS]
    prompt = thesis_prompt(
        FilmShots(carriers=bare, stories=STORIES), scope="a film", occasion="", language="English"
    )

    assert "PEOPLE, those on the most pictures: no one named" in prompt
    assert "1. Robin's birthday (dominant; 4 of 12 shots)\n2. The road" in prompt


class Judge:
    # WHY: stands in for StructureTextJudge's model call; it answers every prompt with `reply`.
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.asked: list[tuple[str, str, dict]] = []

    def ask(self, stage, prompt, max_tokens=0, **contract):
        self.asked.append((stage, prompt, {"max_tokens": max_tokens, **contract}))
        return self.reply


def test_the_thesis_is_one_json_answer_asked_with_its_own_stage_and_budget():
    judge = Judge(json.dumps({"thesis": "Robin's birthday with Kit at home.  Then a lake."}))

    thesis = read_thesis(judge, EXPECTED)

    assert thesis == "Robin's birthday with Kit at home. Then a lake."
    stage, _prompt, contract = judge.asked[0]
    assert stage == "period-thesis"
    assert contract == {"max_tokens": 200, "json_object": True, "json_fields": ("thesis",)}


@pytest.mark.parametrize("reply", ["not json", json.dumps({"thesis": "  "}), "{}"])
def test_an_unusable_thesis_is_refused(reply):
    with pytest.raises(ValueError, match="thesis"):
        read_thesis(Judge(reply), EXPECTED)


def test_the_thesis_prompt_carries_its_version_so_older_answers_are_not_reused():
    prompt = thesis_prompt(shots(), scope="a film", occasion="", language="English")

    assert THESIS_VERSION == "period-thesis-v1"
    assert prompt.splitlines()[0].endswith(THESIS_VERSION)


# --- The thesis-fit vote reads the thesis, not the account ------------------------------------

ACCOUNT = "In June 2030 the family went north; the broad pattern is home days, then travel."
THESIS = "Robin's birthday with Kit at home, then a swim in a lake."


class VoteJudge:
    # WHY: stands in for the model's thesis-fit vote; the prompt it is asked is what is checked.
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            llm=LLMConfig(enabled=True, base_url="http://localhost:8080/v1", model="model-a")
        )
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def ask(self, stage, prompt, **_contract):
        self.calls.append(stage)
        self.prompts.append(prompt)
        return json.dumps({"weak": {}})


class Standing:
    """# WHY: the standing gate's own reader; every picture stands here."""

    def ensure(self, assets, needs=None):
        return None

    def needs(self, asset, weight, story_key=""):
        return 2

    def stands(self, asset, weight, story_key=""):
        return True


class Audience:
    """# WHY: the production audience gate needs detector rows this fixture has no source for."""

    def verdict_of(self, unit):
        return "share"


VOTE_STORY = SimpleNamespace(
    stories=[{"key": "S1", "title": "Robin's birthday", "episodes": ["e1"], "gate": "maybe"}],
    episodes=[SimpleNamespace(key="e1", moments=["m1"])],
    audit={},
)


def _cut():
    return [
        {
            "asset_id": f"a{n}",
            "story_episode": "S1",
            "taken": f"2030-06-04T0{n}:00:00",
            "moment": "m1",
            "seconds": 4.0,
            "kind": "still",
        }
        for n in (1, 2, 3)
    ]


def _vote(account: str, asked: list[str]) -> VoteJudge:
    def thesis_of() -> str:
        asked.append("thesis")
        return THESIS

    polish = ThinPolish(
        store=open_store(), bank_scope="case", read_period=lambda _shots: (account, {})
    )
    cut = _cut()
    judge = VoteJudge()
    polish.polish(
        cut,
        judge=judge,
        gates=PictureAdmission(Standing(), Audience(), thumbnail_hash=lambda _a: None),
        catalogue=polish.catalogue_of(
            VOTE_STORY, {"m1": ["a1", "a2", "a3"]}, drafted=cut, thesis_of=thesis_of
        ),
        contract="contract",
        line_of=lambda asset: f"2030-06-04 | a cake {asset}",
        record=lambda *_args: None,
    )
    return judge


def test_the_vote_judges_every_shot_against_the_thesis_not_the_raw_account():
    asked: list[str] = []

    judge = _vote(ACCOUNT, asked)

    assert judge.prompts
    for prompt in judge.prompts:
        assert f"THE THESIS THIS FILM IS BUILT ON\n{THESIS}\n" in prompt
        assert "broad pattern" not in prompt
    assert asked == ["thesis"]


def test_a_film_whose_period_has_no_account_gets_no_thesis_and_no_vote():
    asked: list[str] = []

    judge = _vote("", asked)

    assert judge.prompts == []
    assert asked == []


def test_a_thesis_the_reader_could_not_give_leaves_the_vote_on_the_account():
    polish = ThinPolish(
        store=open_store(), bank_scope="case", read_period=lambda _shots: (ACCOUNT, {})
    )

    catalogue = polish.catalogue_of(
        VOTE_STORY, {"m1": ["a1"]}, drafted=_cut(), thesis_of=lambda: ""
    )

    assert catalogue is not None
    assert catalogue.thesis == ACCOUNT
