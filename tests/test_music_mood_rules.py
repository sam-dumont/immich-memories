"""A film's music mood follows what the film is, with or without a text model (#2471)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from immich_memories.config.loader import Config

_QUIET = frozenset({"calm", "peaceful", "tender", "sad", "melancholic", "nostalgic"})


def _plan(
    root: Path,
    *,
    memory_type: str,
    kinds: list[str],
    month: str = "03",
    stories: list[dict] | None = None,
    thesis: str = "",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    carriers = [
        {
            "asset_id": f"a{index}",
            "kind": kind,
            "taken": f"2024-{month}-{index % 27 + 1:02d}T12:00:00",
            "story_episode": "s0",
            "seconds": 4,
        }
        for index, kind in enumerate(kinds)
    ]
    story = {"thesis": thesis, "episodes": stories or [{"episode": "s0", "weight": "minor"}]}
    plan = {
        "story": story,
        "carriers": carriers,
        "render_timing": {"policy": {"memory_type": memory_type}},
    }
    (root / "plan.private.json").write_text(json.dumps(plan))
    return root


def _no_model_config(tmp_path: Path) -> Config:
    config = Config(tier="basic")
    config.cache.directory = str(tmp_path / "cache")
    return config


async def _mood(config: Config, attempt: Path):
    from immich_memories.audio.text_mood import mood_for_cut

    # WHY: without a configured model, the HTTP boundary must stay unused.
    with patch("httpx.AsyncClient.post", side_effect=AssertionError("Unexpected LLM call")):
        return await mood_for_cut(config, attempt, ())


_MIXED = ["still", "video", "still", "live-motion", "still", "still", "video", "still"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "memory_type", "month", "stories"),
    [
        (
            "birthday story",
            "monthly_highlights",
            "03",
            [{"episode": "s0", "weight": "major", "occasion": "birthday"}],
        ),
        ("special day", "special_day", "03", None),
        ("trip", "trip", "03", None),
        (
            "trip story in a month",
            "monthly_highlights",
            "03",
            [{"episode": "s0", "weight": "dominant", "kind": "trip", "trip": "away"}],
        ),
        ("holiday", "holiday", "12", None),
        ("summer season", "season", "07", None),
    ],
)
async def test_a_lively_film_gets_a_lively_mood_without_a_model(
    tmp_path, label, memory_type, month, stories
):
    attempt = _plan(
        tmp_path / "a",
        memory_type=memory_type,
        kinds=_MIXED,
        month=month,
        stories=stories,
        thesis="A day",
    )

    choice = await _mood(_no_model_config(tmp_path), attempt)

    assert choice.mood.primary_mood not in _QUIET, label
    assert choice.mood.energy_level in {"medium", "high"}, label
    assert choice.source == "rules_no_model"


@pytest.mark.asyncio
async def test_a_birthday_of_only_stills_still_is_not_calm(tmp_path):
    attempt = _plan(
        tmp_path / "a",
        memory_type="special_day",
        kinds=["still"] * 12,
        stories=[{"episode": "s0", "weight": "major", "occasion": "birthday"}],
    )

    choice = await _mood(_no_model_config(tmp_path), attempt)

    assert choice.mood.primary_mood not in _QUIET


@pytest.mark.asyncio
async def test_a_quiet_month_of_still_photos_gets_calm(tmp_path):
    attempt = _plan(tmp_path / "a", memory_type="monthly_highlights", kinds=["still"] * 14)

    choice = await _mood(_no_model_config(tmp_path), attempt)

    assert choice.mood.primary_mood == "calm"
    assert choice.mood.energy_level == "low"


@pytest.mark.asyncio
async def test_a_month_full_of_video_is_livelier_than_the_same_month_in_stills(tmp_path):
    from immich_memories.audio.generators.ace_step_captions import MOOD_PROFILES

    stills = _plan(tmp_path / "s", memory_type="monthly_highlights", kinds=["still"] * 10)
    videos = _plan(tmp_path / "v", memory_type="monthly_highlights", kinds=["video", "still"] * 5)
    config = _no_model_config(tmp_path)

    quiet, lively = await _mood(config, stills), await _mood(config, videos)

    assert (
        MOOD_PROFILES[lively.mood.primary_mood].energy
        > MOOD_PROFILES[quiet.mood.primary_mood].energy
    )


@pytest.mark.asyncio
async def test_the_note_says_the_rules_chose_and_why(tmp_path):
    from immich_memories.audio.text_mood import music_mood_note

    attempt = _plan(tmp_path / "a", memory_type="trip", kinds=_MIXED, thesis="A trip")
    await _mood(_no_model_config(tmp_path), attempt)

    note = music_mood_note(attempt)

    assert "trip" in note
    assert "no text model configured" in note
    assert "defaults" not in note


def _reply(mood: str, energy: str) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost"),
        json={
            "response": json.dumps(
                {
                    "primary_mood": mood,
                    "energy_level": energy,
                    "tempo_suggestion": "fast",
                    "genre_suggestions": ["pop"],
                    "specific_style": None,
                }
            ),
            "done": True,
        },
    )


def _model_config(tmp_path: Path) -> Config:
    config = Config(
        tier="full",
        llm={
            "enabled": True,
            "base_url": "http://localhost:11434",
            "model": "text-reader",
            "provider": "ollama",
        },
    )
    config.cache.directory = str(tmp_path / "cache")
    return config


@pytest.mark.asyncio
async def test_the_model_reads_the_film_facts_and_is_not_steered_to_calm(tmp_path):
    from immich_memories.audio.text_mood import mood_for_cut

    attempt = _plan(
        tmp_path / "a",
        memory_type="monthly_highlights",
        kinds=_MIXED,
        month="07",
        thesis="Two children sit at a table",
        stories=[{"episode": "s0", "weight": "major", "occasion": "birthday"}],
    )
    # WHY: the text model's HTTP endpoint is the only external boundary.
    with patch("httpx.AsyncClient.post", return_value=_reply("happy", "high")) as post:
        choice = await mood_for_cut(_model_config(tmp_path), attempt, ())

    prompt = post.call_args.kwargs["json"]["prompt"]
    assert choice.source == "cut_text"
    assert choice.mood.primary_mood == "happy"
    assert "birthday" in prompt
    assert "Memory type: monthly highlights" in prompt
    assert "summer" in prompt
    assert "3 of 8 shots move" in prompt
    # The vocabulary is ordered by energy, not alphabetically with calm near the top.
    listed = prompt.split("primary_mood (most to least energetic):")[1].split("\n")[0]
    assert listed.index("energetic") < listed.index("calm")
    assert "calm or peaceful only" in prompt


@pytest.mark.asyncio
async def test_a_failed_model_answer_falls_back_to_the_rules_mood(tmp_path):
    from immich_memories.audio.text_mood import mood_for_cut

    attempt = _plan(tmp_path / "a", memory_type="trip", kinds=_MIXED, thesis="A trip")
    # WHY: the text model's HTTP endpoint answers outside the vocabulary twice.
    with patch("httpx.AsyncClient.post", return_value=_reply("invented", "high")):
        choice = await mood_for_cut(_model_config(tmp_path), attempt, ())

    assert choice.source == "rules_text_unavailable"
    assert choice.mood.primary_mood not in _QUIET


def test_the_rules_mood_reaches_the_generated_caption_with_its_tempo(tmp_path):
    """Render path: no model, a birthday, the generator gets a lively caption at a lively tempo."""
    from immich_memories.audio.generators.ace_step_backend import _caption_for
    from immich_memories.audio.generators.base import GenerationRequest
    from immich_memories.generate_music import resolve_music
    from immich_memories.processing.assembly_config import AssemblyClip

    config = _no_model_config(tmp_path)
    config.ace_step.enabled = True
    attempt = _plan(
        tmp_path / "a",
        memory_type="special_day",
        kinds=["still"] * 6,
        month="10",
        thesis="A birthday",
        stories=[{"episode": "s0", "weight": "major", "occasion": "birthday"}],
    )
    clips = [
        AssemblyClip(
            path=tmp_path / f"c{i}.mp4",
            asset_id=f"a{i}",
            duration=4,
            date="2024-10-12",
            is_photo=i % 2 == 0,
        )
        for i in range(6)
    ]
    seen = {}

    async def generator(**kwargs):
        seen.update(kwargs)

    # WHY: the music generator is the external, GPU-bound boundary; the mood is chosen for real.
    with patch(
        "immich_memories.audio.music_generator.generate_music_for_video", side_effect=generator
    ):
        resolve_music(
            config,
            None,
            False,
            clips,
            tmp_path / "out",
            "special_day",
            bundled_library=tmp_path / "none",
            transition_overlap=0,
            editorial_attempt_dir=attempt,
        )

    scenes = seen["timeline"].build_scenes()
    request = GenerationRequest(
        prompt=scenes[0]["mood"], duration_seconds=60, scenes=scenes, memory_type="special_day"
    )
    lively = _caption_for(request)
    lively_mood = seen["timeline"].clips[0].mood
    quiet = _caption_for(
        GenerationRequest(
            prompt=scenes[0]["mood"].replace(lively_mood, "calm"),
            duration_seconds=60,
            scenes=[{**scenes[0], "mood": scenes[0]["mood"].replace(lively_mood, "calm")}],
            memory_type="special_day",
        )
    )
    assert "serene" not in lively.caption
    assert "mellow" not in lively.caption
    assert lively.bpm > quiet.bpm


@pytest.mark.parametrize("month", [9, 10, 11])
def test_no_autumn_caption_is_told_to_be_mellow(month):
    from immich_memories.audio.generators.ace_step_backend import _caption_for
    from immich_memories.audio.generators.ace_step_captions import MOOD_PROFILES
    from immich_memories.audio.generators.base import GenerationRequest
    from immich_memories.audio.music_generator_models import VideoTimeline

    for mood in MOOD_PROFILES:
        timeline = VideoTimeline.from_clips([(30.0, mood, month)])
        scenes = timeline.build_scenes()
        caption = _caption_for(
            GenerationRequest(prompt=scenes[0]["mood"], duration_seconds=40, scenes=scenes)
        ).caption
        assert "mellow" not in caption, mood


def test_a_quiet_scene_is_not_rewritten_as_upbeat():
    from immich_memories.audio.music_generator_models import VideoTimeline

    scenes = VideoTimeline.from_clips([(30.0, "calm", None)]).build_scenes()

    assert scenes[0]["mood"] == "calm"
