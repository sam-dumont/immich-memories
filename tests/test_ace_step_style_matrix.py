"""Mood x style matrix for generated music (#308).

One caption per mood made every memory of that mood sound the same. Mood now
sets the tempo and emotional register; style picks the genre and instruments,
so the same mood can arrive in several styles. The app picks acoustic, electronic or
piano by itself; the others are played only when a style is named explicitly.
"""

from __future__ import annotations

import pytest

from immich_memories.audio.generators.ace_step_captions import (
    MOOD_PROFILES,
    STYLE_PROFILES,
    build_ace_caption_structured,
)

MOODS = sorted(MOOD_PROFILES)
STYLES = sorted(STYLE_PROFILES)


def test_the_matrix_covers_every_mood_with_every_style():
    assert len(MOODS) == 15
    assert set(STYLES) == {
        "acoustic",
        "electronic",
        "ambient",
        "jazz",
        "rock",
        "orchestral",
        "piano",
        "metal",
    }


@pytest.mark.parametrize("mood", MOODS)
@pytest.mark.parametrize("style", STYLES)
class TestEveryCombinationIsUsable:
    def test_combination_names_its_genre_and_mood(self, mood, style):
        result = build_ace_caption_structured(mood, style=style)

        assert STYLE_PROFILES[style].genre_for(mood) in result.caption
        assert MOOD_PROFILES[mood].word in result.caption

    def test_combination_states_bpm_in_tags_and_field(self, mood, style):
        result = build_ace_caption_structured(mood, style=style)

        assert f"{result.bpm} bpm" in result.caption

    def test_combination_fits_the_api_limit(self, mood, style):
        assert len(build_ace_caption_structured(mood, style=style).caption) < 512


def test_a_calm_memory_stays_calm_within_each_style():
    """Tempo is now per style, so compare within a style rather than across them."""
    for style in STYLES:
        calm = build_ace_caption_structured("calm", style=style).bpm
        energetic = build_ace_caption_structured("energetic", style=style).bpm

        assert calm <= energetic, style


def test_electronic_names_a_tempo_appropriate_subgenre():
    """Its sub-genres are tempo-defined: drum and bass at 70 bpm is not a thing."""
    assert build_ace_caption_structured("energetic", style="electronic").caption.startswith(
        "drum and bass"
    )
    assert build_ace_caption_structured("calm", style="electronic").caption.startswith(
        "downtempo electronic"
    )


def test_repeated_memories_of_one_mood_do_not_all_sound_alike():
    """Without an explicit style the matrix is sampled, so variety emerges."""
    captions = {build_ace_caption_structured("happy").caption for _ in range(40)}

    assert len(captions) > 1


def test_an_explicit_style_is_reproducible():
    first = build_ace_caption_structured("happy", style="acoustic").caption
    again = build_ace_caption_structured("happy", style="acoustic").caption

    assert first == again


def test_an_unknown_style_falls_back_instead_of_failing():
    result = build_ace_caption_structured("happy", style="klezmer-polka")

    assert result.caption
    assert f"{result.bpm} bpm" in result.caption


# The maintainer's listening tests (#308, #2471) kept acoustic, electronic and solo piano; jazz
# trio, rock, orchestral and metal sounded wrong on real films. The app picks only those three.
_VALIDATED = {"acoustic", "electronic", "piano"}


def test_with_no_style_set_every_automatic_pick_is_a_validated_style():
    import random

    from immich_memories.audio.generators.ace_step_captions import pick_style
    from immich_memories.audio.mood_analyzer import VALID_GENRES
    from immich_memories.memory_types.registry import MemoryType

    yields: list[list[str] | None] = [None, [], *([genre] for genre in sorted(VALID_GENRES))]
    kinds = [None, *(kind.value for kind in MemoryType)]
    picks = {
        pick_style(memory_type=kind, genres=genres, rng=random.Random(seed))
        for seed in range(40)
        for kind in kinds
        for genres in yields
    }

    assert picks == _VALIDATED


@pytest.mark.parametrize(
    ("genre", "style"),
    [
        ("jazz", "acoustic"),
        ("piano", "piano"),
        ("orchestral", "piano"),
        ("classical", "piano"),
        ("cinematic", "piano"),
        ("rock", "electronic"),
        ("indie", "electronic"),
        ("metal", "electronic"),
        ("ambient", "electronic"),
    ],
)
def test_a_model_genre_yield_lands_on_a_validated_style(genre, style):
    from immich_memories.audio.generators.ace_step_captions import pick_style

    assert pick_style(genres=[genre]) == style


@pytest.mark.parametrize("style", ["jazz", "metal", "rock", "orchestral", "ambient"])
def test_an_explicit_style_still_wins(style):
    assert STYLE_PROFILES[style].genre in build_ace_caption_structured("happy", style=style).caption


def test_a_model_caption_with_no_style_set_never_names_an_opt_in_genre():
    from immich_memories.audio.mood_analyzer import VideoMood

    for genres in (["jazz"], ["metal"], ["rock"], ["orchestral"], ["indie"]):
        caption = build_ace_caption_structured(
            "happy", mood_detail=VideoMood(primary_mood="happy", genre_suggestions=genres)
        ).caption
        assert caption.split(",")[0] in {
            STYLE_PROFILES["acoustic"].genre,
            STYLE_PROFILES["piano"].genre,
            *STYLE_PROFILES["electronic"].genre_by_mood.values(),
            STYLE_PROFILES["electronic"].genre,
        }, genres
