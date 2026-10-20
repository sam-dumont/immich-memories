"""Mood x style matrix for generated music (#308).

One caption per mood made every memory of that mood sound the same. Mood now
sets the tempo and emotional register; style picks the genre and instruments,
so the same mood can arrive in several styles. The app picks from each mood's Keep/Drop
table by itself; acoustic, jazz, rock, orchestral, ambient and metal only when named.
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
        "lofi",
        "downtempo",
        "neosoul",
        "postrock",
        "funk",
        "citypop",
    }


@pytest.mark.parametrize("mood", MOODS)
@pytest.mark.parametrize("style", STYLES)
class TestEveryCombinationIsUsable:
    def test_combination_names_its_genre_and_mood(self, mood, style):
        result = build_ace_caption_structured(mood, style=style)

        assert STYLE_PROFILES[style].genre_for(mood) in result.caption
        assert MOOD_PROFILES[mood].word in result.caption

    def test_combination_keeps_tempo_out_of_the_caption(self, mood, style):
        result = build_ace_caption_structured(mood, style=style)

        assert result.bpm > 0
        assert "bpm" not in result.caption.lower()

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
    assert "bpm" not in result.caption


# Styles that appear in some mood's Keep/Drop table; everything else is explicit-only.
_NEVER_AUTOMATIC = {"acoustic", "jazz", "rock", "metal", "orchestral", "ambient"}


def test_with_no_style_set_no_opt_in_style_is_ever_picked():
    import random

    from immich_memories.audio.generators.ace_step_captions import pick_style

    picks = {
        pick_style(mood, genres=genres, rng=random.Random(seed))
        for seed in range(60)
        for mood in MOODS
        for genres in (None, ["metal"], ["jazz"], ["rock"], ["orchestral"], ["ambient"], ["folk"])
    }

    assert picks and not picks & _NEVER_AUTOMATIC


def test_every_mood_resolves_to_a_non_empty_table():
    from immich_memories.audio.generators.ace_step_captions import styles_for_mood

    for mood in MOODS:
        assert styles_for_mood(mood), mood


@pytest.mark.parametrize(
    ("mood", "style", "caption"),
    [
        (
            "calm",
            "downtempo",
            "downtempo chill electronica, serene, soft beats, warm synth pads, deep bass",
        ),
        (
            "happy",
            "citypop",
            "80s city pop instrumental, joyful, funky bass, clean electric guitar, rhodes",
        ),
        (
            "tender",
            "neosoul",
            "neo-soul instrumental, tender, rhodes chords, laid-back drums, round bass",
        ),
        (
            "nostalgic",
            "postrock",
            "post-rock instrumental, wistful, clean electric guitars, reverb, building drums",
        ),
        ("energetic", "funk", "instrumental funk, driving, tight bassline, wah guitar, live drums"),
    ],
)
def test_new_style_captions_are_short_with_no_production_tags(mood, style, caption):
    assert build_ace_caption_structured(mood, style=style).caption == caption


@pytest.mark.parametrize(
    ("style", "low", "high"),
    [
        ("downtempo", 80, 100),
        ("neosoul", 75, 95),
        ("postrock", 80, 120),
        ("funk", 95, 118),
        ("citypop", 100, 120),
    ],
)
def test_new_style_tempo_stays_in_its_band(style, low, high):
    for mood in MOODS:
        assert low <= build_ace_caption_structured(mood, style=style).bpm <= high


@pytest.mark.parametrize(
    ("mood", "style"),
    [
        ("energetic", "electronic"),
        ("energetic", "piano"),
        ("happy", "funk"),
        ("happy", "piano"),
        ("happy", "electronic"),
        ("tender", "downtempo"),
    ],
)
def test_a_style_kept_less_than_four_in_ten_is_never_sampled(mood, style):
    import random

    from immich_memories.audio.generators.ace_step_captions import pick_style

    picks = {pick_style(mood, rng=random.Random(seed)) for seed in range(500)}

    assert style not in picks and picks


def test_a_style_kept_exactly_four_in_ten_stays_in():
    from immich_memories.audio.generators.ace_step_captions import styles_for_mood

    assert "lofi" in styles_for_mood("tender")


def test_picks_follow_the_weights():
    import random

    from immich_memories.audio.generators.ace_step_captions import pick_style

    rng = random.Random(11)
    counts = {}
    for _ in range(6000):
        style = pick_style("happy", rng=rng)
        counts[style] = counts.get(style, 0) + 1
    # happy: lofi 4/6, citypop 6/7 (piano, electronic 2/6 and funk 1/3 are below 0.4)
    weights = {"lofi": 5 / 8, "citypop": 7 / 9}
    total = sum(weights.values())
    for style, weight in weights.items():
        assert abs(counts[style] / 6000 - weight / total) < 0.03, style
    assert set(counts) == {"lofi", "citypop"}


def test_a_mood_without_its_own_folder_uses_its_nearest_folders_table():
    from immich_memories.audio.generators.ace_step_captions import styles_for_mood

    assert styles_for_mood("playful") == styles_for_mood("happy")
    assert styles_for_mood("dramatic") == styles_for_mood("energetic")


def test_an_explicit_style_wins_even_when_excluded_or_opt_in():
    from immich_memories.audio.generators.ace_step_captions import pick_style

    assert pick_style("energetic", style="electronic") == "electronic"
    assert pick_style("calm", style="metal") == "metal"


def test_a_genre_suggestion_is_honoured_only_when_the_mood_allows_its_style():
    import random

    from immich_memories.audio.generators.ace_step_captions import pick_style

    assert pick_style("happy", genres=["city pop"]) == "citypop"
    assert pick_style("calm", genres=["piano"]) == "piano"
    # piano and funk are excluded from happy, jazz has no table anywhere: the table decides
    for genre in ("piano", "funk", "jazz"):
        picks = {pick_style("happy", genres=[genre], rng=random.Random(s)) for s in range(200)}
        assert picks == {"lofi", "citypop"}
        assert len(picks) > 1


def test_every_take_of_a_film_shares_one_style():
    import random

    captions = {
        build_ace_caption_structured("tender", rng=random.Random(21)).caption for _ in range(8)
    }

    assert len(captions) == 1


@pytest.mark.parametrize(
    ("genre", "style"),
    [
        ("piano", "piano"),
        ("lofi", "lofi"),
        ("funk", "funk"),
        ("post-rock", "postrock"),
        ("postrock", "postrock"),
        ("downtempo", "downtempo"),
        ("chill", "downtempo"),
        ("neo-soul", "neosoul"),
        ("soul", "neosoul"),
        ("city pop", "citypop"),
    ],
)
def test_the_readers_new_genres_name_their_style(genre, style):
    from immich_memories.audio.generators.ace_step_captions import _GENRE_TO_STYLE
    from immich_memories.audio.mood_analyzer import VALID_GENRES

    assert _GENRE_TO_STYLE[genre] == style
    assert genre in VALID_GENRES


@pytest.mark.parametrize("style", ["jazz", "metal", "rock", "orchestral", "ambient"])
def test_an_explicit_style_still_wins(style):
    assert STYLE_PROFILES[style].genre in build_ace_caption_structured("happy", style=style).caption


def test_solo_piano_caption_is_the_one_rated_best_and_has_no_mood_production_tags():
    result = build_ace_caption_structured("calm", style="piano")

    assert (
        result.caption == "solo piano, serene, felt piano, gentle melody, soft room reverb, hi-fi"
    )


def test_lofi_caption_is_the_one_rated_best_and_has_no_mood_production_tags():
    result = build_ace_caption_structured("nostalgic", style="lofi")

    assert result.caption == (
        "lo-fi hip hop, wistful, dusty drums, warm electric piano, mellow bass, "
        "vinyl crackle, tape saturation"
    )


@pytest.mark.parametrize("mood", MOODS)
def test_lofi_tempo_stays_in_its_band(mood):
    assert 70 <= build_ace_caption_structured(mood, style="lofi").bpm <= 98


def test_a_specific_style_caption_keeps_tempo_out_too():
    from immich_memories.audio.mood_analyzer import VideoMood

    result = build_ace_caption_structured(
        "happy", mood_detail=VideoMood(primary_mood="happy", specific_style="1920s swing")
    )

    assert result.caption.startswith("1920s swing")
    assert "bpm" not in result.caption
