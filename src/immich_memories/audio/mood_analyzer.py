"""The music mood vocabulary, and the mood a film's music is chosen by.

The mood is read from text only (``audio/text_mood.py``): the cut's thesis, its story titles
and the captions banked at ingest. Nothing here looks at a picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What the reader may answer; anything else is refused (whitelist approach).
VALID_MOODS = frozenset(
    {
        "happy",
        "sad",
        "calm",
        "energetic",
        "romantic",
        "dramatic",
        "playful",
        "nostalgic",
        "mysterious",
        "inspiring",
        "peaceful",
        "melancholic",
        "uplifting",
        "tender",
        "exciting",
    }
)

# The music package ships five mood folders; every other mood borrows the nearest one. Bundled
# tracks and the generator's per-mood style table both read this, so a mood sounds like its
# neighbour in both places.
MOOD_FOLDERS = {
    "playful": "happy",
    "inspiring": "happy",
    "uplifting": "happy",
    "peaceful": "calm",
    "exciting": "energetic",
    "dramatic": "energetic",
    "romantic": "tender",
    "sad": "nostalgic",
    "melancholic": "nostalgic",
    "mysterious": "nostalgic",
}

VALID_GENRES = frozenset(
    {
        "acoustic",
        "electronic",
        "cinematic",
        "classical",
        "jazz",
        "pop",
        "rock",
        "ambient",
        "folk",
        "indie",
        "orchestral",
        "piano",
        "guitar",
        "metal",
        "lofi",
        "chillhop",
        "funk",
        "post-rock",
        "postrock",
        "downtempo",
        "chill",
        "neo-soul",
        "soul",
        "city pop",
        "upbeat",
        "relaxing",
    }
)

VALID_ENERGY_LEVELS = frozenset({"low", "medium", "high"})
VALID_TEMPOS = frozenset({"slow", "medium", "fast"})


@dataclass
class VideoMood:
    """The feel a film's music is chosen by."""

    primary_mood: str
    energy_level: str = "medium"  # low, medium, high
    tempo_suggestion: str = "medium"  # slow, medium, fast
    genre_suggestions: list[str] = field(default_factory=list)
    # A free-form genre phrase when this specific event calls for a very specific
    # music style the genre whitelist cannot name ("medieval folk with lute and
    # flute", "mariachi with trumpets", "1920s swing"). None means generic is fine.
    specific_style: str | None = None
