"""A typed film's subtitle says what the film is about, in a few words, or nothing (#2522).

The reader writes it from the period thesis and the title it sits under, when model-written
text is on. A line that names a date, lists places, names someone the facts don't, repeats
the title, or says nothing is not shown: the film then has no subtitle, as before.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

import pytest

from immich_memories.config.loader import Config
from immich_memories.config.models.llm import LLMConfig
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_stories import FilmStories, read_film_stories
from immich_memories.titles.film_subtitle import (
    SUBTITLE_VERSION,
    failed_checks,
    read_subtitle,
    subtitle_prompt,
    subtitle_reader,
)
from immich_memories.titles.film_title import resolve_film_title

THESIS = "Kit learned to swim at Lakeview with Pat. Later, a picnic in the garden."
THESIS_FR = "Kit a appris à nager à Lakeview avec Pat. Puis un pique-nique au jardin."
PLACES = ("Lakeview", "Hillford")


class FakeJudge:
    """The reader at its one boundary: it answers with canned text and keeps the prompts."""

    def __init__(self, answer: str | Exception) -> None:
        self.answer = answer
        self.prompts: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def ask(self, stage: str, prompt: str, max_tokens: int = 260, **_kw: Any) -> str:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _config(locale: str = "en", *, model_text: bool = True, model: bool = True) -> Config:
    config = Config()
    config.title_screens = config.title_screens.model_copy(
        update={"locale": locale, "llm_titles": model_text}
    )
    if model:
        config.llm = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )
    return config


def _summer(
    judge: FakeJudge | None,
    *,
    locale: str = "en",
    thesis: str | None = THESIS,
    enabled: bool | None = None,
    model_text: bool = True,
    model: bool = True,
    subtitle: str | None = None,
) -> tuple[str | None, str | None, int]:
    """A summer film's (title, subtitle) and how many readers were made for it."""
    made: list[FakeJudge] = []

    def reader() -> FakeJudge:
        assert judge is not None
        made.append(judge)
        return judge

    title, sub, _source = resolve_film_title(
        enabled=enabled,
        title_override=None,
        subtitle_override=subtitle,
        clips=[],
        config=_config(locale, model_text=model_text, model=model),
        memory_type="season",
        date_range=DateRange(datetime(2025, 6, 1), datetime(2025, 8, 31, 23, 59)),
        person_names=[],
        memory_preset_params={"season": "summer", "hemisphere": "north"},
        stories=FilmStories(thesis=thesis, places=PLACES),
        subtitle_reader=reader if judge is not None else None,
    )
    return title, sub, len(made)


# ------------------------------------------------------------------ the prompt


def test_the_prompt_asks_a_few_words_from_the_thesis_and_the_title_and_allows_none():
    prompt = subtitle_prompt(title="Summer 2025", thesis=THESIS, language="French")

    first_line = prompt.splitlines()[0]
    assert SUBTITLE_VERSION == "film-subtitle-v1"
    assert SUBTITLE_VERSION in first_line
    assert '"Summer 2025"' in first_line
    assert f"Its period: {THESIS}" in prompt
    assert "2 to 6 words in French" in prompt
    assert "answer an empty subtitle" in prompt
    assert prompt.rstrip().endswith('JSON only: {"subtitle":"..."}')
    # About 600 characters for a made-up film: small enough for the small reader.
    assert len(prompt) < 700


# ------------------------------------------------------------------ the checks


@pytest.mark.parametrize(
    ("subtitle", "locale", "failed"),
    [
        ("Kit learns to swim", "en", ()),
        ("Kit's swim in July", "en", ("no date",)),
        ("A Saturday at the lake", "en", ("no date",)),
        ("Kit learns to swim, 2025", "en", ("no date",)),
        ("Le plongeon de Kit, 1er juillet", "fr", ("no date",)),
        ("Les samedis au lac", "fr", ("no date",)),
        ("A swim at Lakeview", "en", ()),
        ("Lakeview and Hillford", "en", ("no place list",)),
        ("Kit and Pat at the lake", "en", ()),
        ("Kit and Robin at the lake", "en", ("names backed",)),
        ("Summer of Kit", "en", ("not the title",)),
        ("Time together at the lake", "en", ("not generic",)),
        ("Le premier plongeon de Kit", "fr", ()),
        ("Journées et sorties en famille", "fr", ("not filler only",)),
        ("Days at home and outings", "en", ("not filler only",)),
    ],
)
def test_each_check_passes_or_fails_a_subtitle(subtitle, locale, failed):
    thesis = THESIS_FR if locale == "fr" else THESIS
    title = "Été 2025 · Kit" if locale == "fr" else "Kit · Summer 2025"

    got = failed_checks(subtitle, title=title, thesis=thesis, places=PLACES, locale=locale)

    assert got == failed


def test_a_title_said_again_word_for_word_is_a_repeat():
    got = failed_checks(
        "Summer 2025", title="Summer 2025", thesis=THESIS, places=PLACES, locale="en"
    )

    assert "not the title" in got


# ------------------------------------------------------------------ the answer


@pytest.mark.parametrize(
    ("answer", "shown"),
    [
        ('{"subtitle": "Kit learns to swim"}', "Kit learns to swim"),
        ('{"subtitle": "  Kit learns to swim  "}', "Kit learns to swim"),
        ('{"subtitle": ""}', None),
        ('{"subtitle": null}', None),
        ('{"subtitle": "Days at home and outings"}', None),
        ('{"subtitle": "Lakeview and Hillford"}', None),
        ('{"subtitle": "' + "Kit learns to swim " * 8 + '"}', None),
        ("not json at all", None),
    ],
)
def test_the_answer_is_shown_only_when_it_passes_every_check(answer, shown):
    judge = FakeJudge(answer)

    got = read_subtitle(judge, title="Summer 2025", thesis=THESIS, places=PLACES, locale="en")

    assert got == shown
    assert len(judge.prompts) == 1


def test_a_canned_answer_reaches_the_title_cards_subtitle():
    judge = FakeJudge('{"subtitle": "Kit learns to swim"}')

    title, subtitle, made = _summer(judge)

    assert (title, subtitle, made) == ("Summer 2025", "Kit learns to swim", 1)
    assert '"Summer 2025"' in judge.prompts[0]
    assert THESIS in judge.prompts[0]


def test_a_french_film_asks_in_french_under_its_french_title():
    judge = FakeJudge('{"subtitle": "Le premier plongeon de Kit"}')

    title, subtitle, _made = _summer(judge, locale="fr", thesis=THESIS_FR)

    assert (title, subtitle) == ("Été 2025", "Le premier plongeon de Kit")
    assert "in French" in judge.prompts[0]


@pytest.mark.parametrize("answer", ['{"subtitle": ""}', '{"subtitle": "Summer 2025"}'])
def test_an_empty_or_refused_answer_leaves_no_subtitle(answer):
    title, subtitle, made = _summer(FakeJudge(answer))

    assert (title, subtitle, made) == ("Summer 2025", None, 1)


# ------------------------------------------------------------------ off


@pytest.mark.parametrize(
    "off",
    [
        {"model_text": False},
        {"model": False},
        {"enabled": False},
        {"thesis": None},
        {"thesis": ""},
    ],
    ids=["model-text-off", "no-reader-configured", "no-llm-title", "no-thesis", "empty-thesis"],
)
def test_with_model_text_off_or_nothing_to_read_nothing_is_asked(off):
    judge = FakeJudge('{"subtitle": "Kit learns to swim"}')

    title, subtitle, made = _summer(judge, **off)

    assert (title, subtitle, made) == ("Summer 2025", None, 0)
    assert judge.prompts == []


def test_llm_title_asks_for_one_run_with_model_text_off():
    judge = FakeJudge('{"subtitle": "Kit learns to swim"}')

    assert _summer(judge, model_text=False, enabled=True) == (
        "Summer 2025",
        "Kit learns to swim",
        1,
    )


def test_no_reader_for_the_run_means_no_subtitle():
    assert _summer(None) == ("Summer 2025", None, 0)


def test_a_typed_subtitle_wins_and_nothing_is_asked():
    judge = FakeJudge('{"subtitle": "Kit learns to swim"}')

    assert _summer(judge, subtitle="By the sea") == ("Summer 2025", "By the sea", 0)


@pytest.mark.parametrize("failure", [OSError("unreachable"), RuntimeError("reader gave up")])
def test_a_reader_that_fails_leaves_the_title_and_no_subtitle(failure):
    title, subtitle, made = _summer(FakeJudge(failure))

    assert (title, subtitle, made) == ("Summer 2025", None, 1)


def test_a_trip_keeps_its_own_title_path():
    """Only typed films get this subtitle: a trip is named by its own prompt."""
    judge = FakeJudge('{"subtitle": "Kit learns to swim"}')

    _title, subtitle, _source = resolve_film_title(
        enabled=False,
        title_override=None,
        clips=[],
        config=_config(),
        memory_type="trip",
        date_range=DateRange(datetime(2025, 6, 1), datetime(2025, 6, 8)),
        person_names=[],
        stories=FilmStories(thesis=THESIS),
        subtitle_reader=lambda: judge,
    )

    assert subtitle is None
    assert judge.prompts == []


# ------------------------------------------------------------------ what the title reads


def test_the_cuts_thesis_and_every_place_are_read_from_its_attempt(tmp_path):
    from immich_memories.operations.storyboard import PLAN_FILE

    plan = {
        "story": {
            "thesis": "Kit's summer by the lake.",
            "episodes": [
                {"title": "A swim", "weight": "major", "places": ["Lakeview, Somewhere"]},
                {"title": "A walk", "weight": "glimpse", "places": ["Hillford", ""]},
            ],
        }
    }
    (tmp_path / PLAN_FILE).write_text(json.dumps(plan))
    decisions = tmp_path / "derived-decisions"
    decisions.mkdir()
    (decisions / "film-summary.private.json").write_text(
        json.dumps({"version": "film-summary-v4", "tier": "full", "thesis": THESIS})
    )

    stories = read_film_stories(tmp_path)

    assert stories.thesis == THESIS
    assert stories.places == ("Lakeview", "Hillford")
    assert stories.summary == "Kit's summer by the lake."


def test_a_cut_summarised_without_a_model_has_no_thesis(tmp_path):
    from immich_memories.operations.storyboard import PLAN_FILE

    (tmp_path / PLAN_FILE).write_text(json.dumps({"story": {"episodes": []}}))
    decisions = tmp_path / "derived-decisions"
    decisions.mkdir()
    (decisions / "film-summary.private.json").write_text('{"tier": "off", "summary": ""}')

    assert read_film_stories(tmp_path).thesis is None


def test_a_run_without_an_attempt_has_no_reader(tmp_path):
    assert subtitle_reader(_config(), None) is None
    made = subtitle_reader(_config(), tmp_path)
    assert callable(cast(Any, made))


# ------------------------------------------------------------------ the provider probe


@pytest.mark.parametrize(
    ("subtitle", "valid"),
    [("Avery's fifth birthday cake", True), ("", False), ("Days at home", False)],
)
def test_the_conformance_probe_reads_the_real_reader_path(monkeypatch, subtitle, valid):
    import httpx

    from immich_memories.conformance.cases import cases
    from immich_memories.conformance.runtime import run_case

    def reply(_request: httpx.Request) -> httpx.Response:
        content = json.dumps({"subtitle": subtitle})
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: replace only the provider HTTP response; the judge, bank and checks stay real.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    probes = cases(LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1"))

    result = run_case(next(case for case in probes if case.name == "film subtitle"))

    assert result.valid is valid, result.quality
    assert result.calls == 1
