"""#2594: one short question per episode, with who and where said once.

The slim block won a measured A/B against the old lean prompt on a real library (76 episodes,
same small reader): a third of the prompt, a third of the time, more answers naming a person or a
town and far fewer generic ones. These tests hold the shape that won, on a made-up episode.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from immich_memories.analysis.corpus.admission import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.corpus.groups import project_episode_groups
from immich_memories.analysis.reading.episode_answers import (
    EpisodeRequestScope,
    read_response_result,
)
from immich_memories.analysis.reading.episode_prompt import (
    TEXT_EPISODE_LEAN_PROMPT_VERSION,
    TEXT_EPISODE_PROMPT_VERSION,
    EpisodePromptFacts,
    episode_prompt,
)
from immich_memories.analysis.reading.episode_reader import CachedTextEpisodeReader
from immich_memories.store.episode_readings import (
    BankedEpisodeReading,
    EpisodeReadingIdentity,
    EpisodeReadingProducer,
    EpisodeReadingStore,
    EpisodeRepresentative,
)
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset
from tests.test_text_episode_reader import _AnnotationLines

# Who is on which picture, by count: Kit on all 20, Lou on one.
_ON_PICTURES = {"Kit": 20, "Robin": 16, "Alex": 12, "Jo": 8, "Max": 3, "Lou": 1}
_WHO = {
    "Kit": "Kit Doe (daughter of library owner; aged 6; inner circle)",
    "Robin": "Robin Doe (library owner; inner circle)",
    "Alex": "Alex Roe (friend; aged 7)",
    "Jo": "Jo Roe (friend's parent)",
    "Max": "Max Poe (cousin; aged 9)",
    "Lou": "Lou Poe (aunt)",
}
_NOISE = (
    "resolution",
    "exposure",
    "subject-framing",
    "% of the frame",
    "duration",
    "reencode",
    "SOFT",
    "location=",
    "people=",
    "children=",
    "inner circle",
    "STARRED by",
    "14:0",
)


def _line(n: int) -> str:
    people = "; ".join(_WHO[name] for name, count in _ON_PICTURES.items() if n < count)
    return " | ".join(
        (
            f"2030-05-04 14:{n:02d}",
            "LIVE PHOTO (renders as a still)" if n % 5 == 0 else "VIDEO 12s raw",
            f"Children around a birthday cake with candles, picture {n}",
            "setting: a kitchen",
            "exposure: dim",
            "at Townville, Some Region, Somewhere",
            f"with {people}",
            "subject-framing:close (12.50% of the frame, inside the frame, the largest face)",
            "activity=eating-drinking, children=several, location=indoor, people=group",
            *(("STARRED by the photographer",) if n == 3 else ()),
            "SOFT (blurry)",
            "resolution:4032x3024",
            "duration:12.000s",
            "reencode-suspected",
        )
    )


_IDS = tuple(f"p{n:02d}" for n in range(20))
_LINES = {asset: _line(n) for n, asset in enumerate(_IDS)}


def _scope(ids: tuple[str, ...] = _IDS) -> EpisodeRequestScope:
    return EpisodeRequestScope(
        identity=EpisodeReadingIdentity(group_id="e1", producer_key="p", evidence_key="k"),
        full_asset_ids=ids,
        page_asset_ids=ids,
        page_number=1,
        page_count=1,
    )


def _prompt(*, lean: bool = True) -> str:
    return episode_prompt(_scope(), EpisodePromptFacts(lines=_LINES, lean=lean))


def _block_line(prompt: str, head: str) -> str:
    return next(line for line in prompt.splitlines() if line.startswith(head))


def test_the_film_question_reads_one_episode_and_asks_no_cull() -> None:
    prompt = _prompt()

    assert prompt.count("EPISODE:") == 1
    assert _block_line(prompt, "EPISODE:") == "EPISODE: 20 pictures, 2030-05-04"
    assert prompt.count("- what_happened:") == 1
    assert "cull" not in prompt.casefold()
    assert '"episodes"' not in prompt


def test_the_town_line_holds_the_town_only() -> None:
    assert _block_line(_prompt(), "Town:") == "Town: Townville"


def test_the_people_line_says_who_the_four_most_seen_are_once_then_counts_the_rest() -> None:
    people = _block_line(_prompt(), "People:")

    assert people == (
        "People: Kit (daughter of library owner, aged 6); Robin (library owner); "
        "Alex (friend, aged 7); Jo (friend's parent); and 2 others"
    )


def test_a_picture_line_names_people_by_first_name_and_says_what_it_shows() -> None:
    first = _block_line(_prompt(), "1. ")

    assert first == (
        "1. Children around a birthday cake with candles, picture 0; a live photo; a kitchen; "
        "a meal; with Kit, Robin, Alex, Jo, Max, Lou"
    )
    assert "4. " in _prompt() and "starred" in _block_line(_prompt(), "4. ")
    assert "(daughter" not in _block_line(_prompt(), "2. ")


@pytest.mark.parametrize("lean", [True, False])
def test_the_noise_fields_never_reach_the_prompt(lean: bool) -> None:
    prompt = _prompt(lean=lean)

    assert [noise for noise in _NOISE if noise in prompt] == []


def test_a_twenty_picture_episode_stays_under_the_size_budget() -> None:
    """The old lean prompt over raw lines was 13,352 characters for this episode.

    The measured question alone is about 3,300 here; the record ask the film reads back adds
    about 700, and library preparation's Cull ask about 300 more.
    """
    assert len(_prompt()) < 4_200
    assert len(_prompt(lean=False)) < 4_500


def test_library_preparation_keeps_its_cull_and_record_questions_on_the_same_block() -> None:
    full, lean = _prompt(lean=False), _prompt()

    assert "- cull:" in full and "- notable_moments:" in full
    assert "- notable_moments:" in lean
    assert full.split("EPISODE:", 1)[1] == lean.split("EPISODE:", 1)[1]


def test_a_place_with_only_coordinates_and_a_picture_with_no_one_add_no_lines() -> None:
    lines = {"a": "2030-05-04 09:00 | a view over a lake | at 50.123,4.567"}
    prompt = episode_prompt(_scope(("a",)), EpisodePromptFacts(lines=lines, lean=True))

    assert "Town:" not in prompt and "People:" not in prompt
    assert _block_line(prompt, "1. ") == "1. a view over a lake"


def test_the_albums_holding_the_episode_stay_a_fact_line() -> None:
    prompt = episode_prompt(
        _scope(("p00",)),
        EpisodePromptFacts(lines=_LINES, album_names=lambda _ids: ("Kit turns six",), lean=True),
    )

    assert "\nAlbums: Kit turns six\n" in prompt


_SLIM_ANSWER = json.dumps(
    {
        "what_happened": "Kit blew out the candles on her birthday cake with Robin in Townville.",
        "representatives": [
            {"picture": 4, "reason": "starred candle moment"},
            {"picture": 1, "reason": "the cake"},
        ],
    }
)


def test_a_slim_answer_reads_through_the_real_parser() -> None:
    response = read_response_result(_SLIM_ANSWER, (_scope(),))

    assert response.problems == {}
    (reading,) = response.readings
    assert reading.what_happened.startswith("Kit blew out the candles")
    assert reading.representatives == (
        EpisodeRepresentative("p03", "starred candle moment"),
        EpisodeRepresentative("p00", "the cake"),
    )
    assert reading.notable_moments == () and reading.cull_decisions == ()


def test_a_slim_answer_with_records_and_rejects_reads_them_by_picture_number() -> None:
    raw = json.dumps(
        {
            "what_happened": "A birthday cake in a kitchen.",
            "representatives": [{"picture": 1, "reason": "the cake"}],
            "notable_moments": [{"picture": 2, "reason": "sixth birthday candles"}],
            "cull": [{"picture": 3, "bucket": "failed"}],
        }
    )

    (reading,) = read_response_result(raw, (_scope(),)).readings

    assert reading.notable_moments == (EpisodeRepresentative("p01", "sixth birthday candles"),)
    assert [(c.asset_id, c.bucket) for c in reading.cull_decisions] == [("p02", "failed")]


def test_a_slim_answer_naming_a_picture_past_the_block_is_not_banked() -> None:
    raw = json.dumps(
        {"what_happened": "A cake.", "representatives": [{"picture": 21, "reason": "the cake"}]}
    )

    response = read_response_result(raw, (_scope(),))

    assert response.readings == ()
    assert "no usable representative" in next(iter(response.problems.values()))


def _producer(prompt_version: str) -> EpisodeReadingProducer:
    return EpisodeReadingProducer(
        model_id="a-small-reader",
        prompt_version=prompt_version,
        schema_version="episode-reading-text-v1",
        annotation_renderer_version="annotation-line-v1",
        annotation_versions=("description:student-v1",),
    )


def _projections():
    noon = datetime(2030, 5, 4, 12, tzinfo=UTC)
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope()),
        EditorialDependencies(
            source_fetcher=lambda _scope: tuple(
                make_asset(asset, file_created_at=noon + timedelta(minutes=n))
                for n, asset in enumerate(_IDS[:3])
            )
        ),
    )
    return project_episode_groups(prepared, prepared.candidate_ids)


# The versions banked readings were filed under before the slim prompt.
_OLD_VERSIONS = (
    "episode-prompt-v4-notable-bar/f8c1f2fe52cb116b",
    "episode-prompt-v4-lean/15fd38fbd63d1b43",
)


@pytest.mark.parametrize(
    ("old", "new", "lean"),
    [
        (_OLD_VERSIONS[0], TEXT_EPISODE_PROMPT_VERSION, False),
        (_OLD_VERSIONS[1], TEXT_EPISODE_LEAN_PROMPT_VERSION, True),
    ],
)
def test_a_reading_banked_under_the_old_prompt_is_read_again(old, new, lean) -> None:
    lines = {asset: _LINES[asset] for asset in _IDS[:3]}
    group = _projections()[0].group
    store = EpisodeReadingStore(annotation_store())
    store.remember(
        (
            BankedEpisodeReading(
                identity=EpisodeReadingIdentity.from_annotations(
                    group_id=group.group_id,
                    producer_key=_producer(old).key(),
                    annotation_lines=lines,
                ),
                full_asset_ids=group.candidate_ids,
                what_happened="An old reading.",
                representatives=(EpisodeRepresentative("p00", "old"),),
                cull_decisions=(),
            ),
        )
    )
    asked: list[str] = []

    def requester(prompt: str) -> str:
        asked.append(prompt)
        return _SLIM_ANSWER.replace('"picture": 4', '"picture": 3')

    result = CachedTextEpisodeReader(
        store=store,
        producer=_producer(new),
        annotations=_AnnotationLines(lines),
        requester=requester,
        lean=lean,
    ).read(_projections())

    assert new not in _OLD_VERSIONS
    assert len(asked) == 1 and result.episodes[0].cache_hit is False
    reading = result.episodes[0].reading
    assert reading is not None and reading.what_happened.startswith("Kit blew out")

    # the fresh reading is banked under the new prompt: the next run asks nothing
    def forbidden(_prompt: str) -> str:
        raise AssertionError("a reading banked under this prompt answers it")

    again = CachedTextEpisodeReader(
        store=store,
        producer=_producer(new),
        annotations=_AnnotationLines(lines),
        requester=forbidden,
        lean=lean,
    ).read(_projections())
    assert again.actual_calls == 0 and again.episodes[0].reading == reading


def test_several_episodes_are_asked_one_per_call() -> None:
    noon = datetime(2030, 5, 4, 12, tzinfo=UTC)
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope()),
        EditorialDependencies(
            source_fetcher=lambda _scope: (
                make_asset("morning", file_created_at=noon - timedelta(hours=6)),
                make_asset("evening", file_created_at=noon + timedelta(hours=6)),
            )
        ),
    )
    projections = project_episode_groups(prepared, prepared.candidate_ids)
    assert len(projections) == 2
    asked: list[str] = []

    def requester(prompt: str) -> str:
        asked.append(prompt)
        return json.dumps(
            {"what_happened": "A day.", "representatives": [{"picture": 1, "reason": "it"}]}
        )

    result = CachedTextEpisodeReader(
        store=EpisodeReadingStore(annotation_store()),
        producer=_producer(TEXT_EPISODE_LEAN_PROMPT_VERSION),
        annotations=_AnnotationLines({"morning": "a breakfast", "evening": "a sunset"}),
        requester=requester,
        lean=True,
    ).read(projections)

    assert len(asked) == 2
    assert all(prompt.count("EPISODE: 1 picture\n") == 1 for prompt in asked)
    assert all(episode.reading is not None for episode in result.episodes)
