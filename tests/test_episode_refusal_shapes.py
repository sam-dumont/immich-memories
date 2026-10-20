"""#2682: the answer shapes behind the recorded episode refusals, read or explained.

Each shape is one a small local reader actually wrote for a refused episode (wording replaced,
structure kept). At temperature 0 an identical retry got the identical answer back, so the
retry has to say what was wrong.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from immich_memories.analysis.corpus.admission import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.analysis.corpus.groups import project_episode_groups
from immich_memories.analysis.reading.episode_answers import EpisodeRequestScope
from immich_memories.analysis.reading.episode_paging import TextEpisodeRequestLimits
from immich_memories.analysis.reading.episode_prompt import (
    EpisodePromptFacts,
    episode_prompt,
)
from immich_memories.analysis.reading.episode_reader import CachedTextEpisodeReader
from immich_memories.db.tables import editorial_episode_refusals
from immich_memories.store.episode_readings import (
    EpisodeReadingIdentity,
    EpisodeReadingProducer,
    EpisodeReadingStore,
)
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset
from tests.test_text_episode_reader import _AnnotationLines

_HEAD = '```json\n{\n"schema_version":"episode-reading-text-v1",\n"episodes":['
_TAIL = "\n]\n}\n```"
_ROW = (
    '\n{\n"episode":1,\n"what_happened":"A family day at the park.",'
    '"representatives":[{"asset":1,"reason":"Starred photo of a child"}],\n'
    '"notable_moments":[]\n}'
)
GOOD = _HEAD + _ROW + _TAIL
# The answer read "Return [] when no line shows such a record" as the whole answer.
EMPTY = _HEAD + "]\n}\n```"
TRAILING_COMMA = _HEAD + _ROW.replace('"notable_moments":[]\n}', '"notable_moments":[],\n}') + _TAIL
# One episode split into its situations, numbered as if they were episodes.
SPLIT = _HEAD + _ROW + ",\n" + _ROW.replace('"episode":1', '"episode":2') + _TAIL
DOUBLED_QUOTE = _HEAD + _ROW.replace('"reason":"Starred', '""reason":"Starred') + _TAIL
STRAY_TOKEN = _HEAD + _ROW.replace('"representatives":[', '"representatives": stray[') + _TAIL
SWAPPED_BRACKETS = (
    _HEAD
    + _ROW.replace(
        '"notable_moments":[]\n}', '"notable_moments":[{"asset":1,"reason":"A slide"}\n}]'
    )
    + _TAIL
)


def _reader(requester, store=None) -> tuple[CachedTextEpisodeReader, tuple]:
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope()),
        EditorialDependencies(source_fetcher=lambda _scope: (make_asset("picture"),)),
    )
    reader = CachedTextEpisodeReader(
        store=store or EpisodeReadingStore(annotation_store()),
        producer=EpisodeReadingProducer(
            model_id="a-small-reader",
            prompt_version="episode-prompt-v4-lean",
            schema_version="episode-reading-text-v1",
            annotation_renderer_version="annotation-line-v1",
            annotation_versions=("description:student-v1",),
        ),
        annotations=_AnnotationLines({"picture": "a child on a slide in a park"}),
        requester=requester,
        limits=TextEpisodeRequestLimits(unread_retry_rounds=2),
        lean=True,
    )
    return reader, project_episode_groups(prepared, prepared.candidate_ids)


@pytest.mark.parametrize(
    ("first", "named"),
    [
        (EMPTY, '"episodes" list was empty'),
        (SPLIT, 'had 2 entries in "episodes" for 1 episode'),
        (DOUBLED_QUOTE, "not valid JSON"),
        (STRAY_TOKEN, "not valid JSON"),
        (SWAPPED_BRACKETS, "not valid JSON"),
    ],
)
def test_a_recorded_failure_shape_is_read_on_a_retry_that_names_it(first, named):
    prompts: list[str] = []

    def requester(prompt: str) -> str:
        prompts.append(prompt)
        return first if len(prompts) == 1 else GOOD

    reader, projections = _reader(requester)

    result = reader.read(projections)

    assert result.episodes[0].reading is not None
    assert len(prompts) == 2
    assert prompts[1] != prompts[0]
    assert "Your last answer could not be used: the answer" in prompts[1]
    assert named in prompts[1]


def test_a_trailing_comma_is_read_without_asking_again():
    prompts: list[str] = []
    reader, projections = _reader(lambda prompt: (prompts.append(prompt), TRAILING_COMMA)[1])

    result = reader.read(projections)

    assert result.episodes[0].reading is not None
    assert result.episodes[0].reading.what_happened == "A family day at the park."
    assert len(prompts) == 1


def test_an_answer_that_never_parses_is_refused_with_its_problem_and_its_words():
    store = annotation_store()
    prompts: list[str] = []
    reader, projections = _reader(
        lambda prompt: (prompts.append(prompt), DOUBLED_QUOTE)[1], EpisodeReadingStore(store)
    )

    result = reader.read(projections)

    assert result.episodes[0].reading is None
    assert len(prompts) == 3  # the question, then two retries naming the problem
    with store.connect() as connection:
        reason, excerpt = connection.execute(
            sa.select(
                editorial_episode_refusals.c.reason, editorial_episode_refusals.c.answer_excerpt
            )
        ).one()
    assert "not valid JSON (Expecting ':' delimiter" in reason
    assert excerpt == DOUBLED_QUOTE


def test_a_long_answer_keeps_a_bounded_excerpt_with_both_ends():
    from immich_memories.analysis.reading.episode_reader import answer_excerpt

    answer = "{" + "x" * 5_000 + "}"

    excerpt = answer_excerpt(answer, limit=1_200)

    assert len(excerpt) == 1_200
    assert excerpt.startswith("{x") and excerpt.endswith("x}")


def test_the_lean_question_says_which_list_is_usually_empty():
    """249 of 1,673 recorded answers were `"episodes":[]`: a bare "Return []" read as the answer."""
    ids = ("picture",)
    scope = EpisodeRequestScope(EpisodeReadingIdentity("e", "p", "k"), ids, ids, 1, 1)
    prompt = episode_prompt((scope,), EpisodePromptFacts({"picture": "a line"}, lean=True))

    assert "notable_moments is [] when no line shows" in prompt
    assert "Return []" not in prompt


def test_the_shapes_are_what_was_recorded():
    """Guard the fixtures themselves: each broken shape really is broken JSON, or empty."""
    for shape in (DOUBLED_QUOTE, STRAY_TOKEN, SWAPPED_BRACKETS, TRAILING_COMMA):
        body = shape.removeprefix("```json").removesuffix("```")
        with pytest.raises(json.JSONDecodeError):
            json.loads(body)
    assert json.loads(EMPTY.removeprefix("```json").removesuffix("```"))["episodes"] == []
