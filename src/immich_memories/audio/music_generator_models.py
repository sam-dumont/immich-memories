"""Data models for music generation.

Contains timeline, mood, stem, and result dataclasses used by
the MusicGen API client and high-level generation functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

# =============================================================================
# Seasonal Prompts
# =============================================================================

SEASONAL_MOODS = {
    1: "winter bright energetic",
    2: "late winter hopeful driving",
    3: "spring fresh bouncy uplifting",
    4: "spring bright cheerful playful",
    5: "late spring vibrant energetic fun",
    6: "early summer carefree sunny groovy",
    7: "midsummer bright joyful energetic",
    8: "summer sunny upbeat fun",
    9: "early autumn warm upbeat groovy",
    10: "autumn cozy upbeat rhythmic",
    11: "late autumn upbeat warm",
    12: "winter holiday festive bouncy fun",
}


def get_seasonal_prompt(month: int, hemisphere: str = "north") -> str:
    """Generate seasonal mood keywords for a month.

    Args:
        month: Month number (1-12)
        hemisphere: "north" or "south" (inverts seasons for southern hemisphere)

    Returns:
        Seasonal mood string for music generation prompt
    """
    if not 1 <= month <= 12:
        return ""

    # Invert seasons for southern hemisphere
    if hemisphere.lower() == "south":
        month = (month + 6 - 1) % 12 + 1

    return SEASONAL_MOODS.get(month, "")


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class ClipMood:
    """Mood information for a single video clip."""

    duration: float  # Clip duration in seconds
    mood: str  # Primary mood (e.g., "happy", "nostalgic")
    has_transition_after: bool = False  # Month divider after this clip
    transition_duration: float = 2.0  # Duration of transition (if any)
    month: int | None = None  # Month number (1-12) for seasonal prompts


# Once the film is assembled its length is known. The music runs this much past it so
# the mixer trims the track: a track even slightly short is looped with a crossfade.
MUSIC_TAIL_SECONDS = 1.0
# The MusicGen soundtrack service takes 5-120 s per scene and at most 40 scenes.
_SCENE_MIN_SECONDS = 5
_SCENE_MAX_SECONDS = 120
_MAX_SCENES = 40
# A run of clips shorter than this is one clip's mood flicker, not a section of the film.
_MIN_CHAPTER_SECONDS = 20.0


@dataclass
class _Chapter:
    """A run of clips the soundtrack treats as one section."""

    mood: str
    seconds: float


@dataclass
class VideoTimeline:
    """Timeline info for music duration calculation."""

    title_duration: float = 3.5  # Opening title screen
    ending_duration: float = 7.0  # Ending screen (fade to white)
    fade_buffer: float = 5.0  # Extra for smooth fade out (5s as requested)

    # Per-clip mood information
    clips: list[ClipMood] = field(default_factory=list)

    # The assembled film's real length, when the caller has it. Clip durations
    # overlap at every crossfade, so their sum overstates the film.
    film_duration: float | None = None

    @property
    def content_duration(self) -> float:
        """Total content duration including transitions."""
        total = 0.0
        for clip in self.clips:
            total += clip.duration
            if clip.has_transition_after:
                total += clip.transition_duration
        return total

    @property
    def total_duration(self) -> float:
        """Total music duration needed."""
        return self.title_duration + self.content_duration + self.ending_duration + self.fade_buffer

    @property
    def music_duration(self) -> float:
        """How much music the film needs: its real length when known, else the clip estimate."""
        if self.film_duration:
            return self.film_duration + MUSIC_TAIL_SECONDS
        return self.total_duration

    def build_scenes(self, hemisphere: str = "north") -> list[dict]:
        """One scene per chapter of the film, summing to ``music_duration``.

        A chapter is a run of clips with one mood that no month divider breaks.
        Runs shorter than a short section join their neighbour, so a clip whose
        mood flickers does not get a five-second fragment of its own (#2472). A
        chapter longer than the soundtrack service takes is split into equal
        scenes with the same mood, which the service continues from each other.

        Args:
            hemisphere: "north" or "south" for seasonal prompt generation

        Returns:
            List of {"mood": str, "duration": int} for soundtrack API
        """
        total = self.music_duration
        if not self.clips:
            return [{"mood": "upbeat", "duration": max(_SCENE_MIN_SECONDS, round(total))}]

        chapters = _merge_short_chapters(self._chapters(hemisphere))
        scale = total / sum(chapter.seconds for chapter in chapters)
        scenes: list[tuple[str, float]] = []
        for chapter in chapters:
            pieces = max(1, math.ceil(chapter.seconds * scale / _SCENE_MAX_SECONDS))
            scenes.extend([(chapter.mood, chapter.seconds * scale / pieces)] * pieces)
        return _whole_second_scenes(scenes, round(total))

    def _chapters(self, hemisphere: str) -> list[_Chapter]:
        """Runs of clips with one scene mood and no divider between them."""
        chapters: list[_Chapter] = []
        divider_before = False
        for i, clip in enumerate(self.clips):
            seconds = clip.duration
            if i == 0:
                seconds += self.title_duration
            if clip.has_transition_after:
                seconds += clip.transition_duration
            if i == len(self.clips) - 1:
                seconds += self.ending_duration + self.fade_buffer
            mood = _scene_mood(clip, hemisphere)
            if chapters and chapters[-1].mood == mood and not divider_before:
                chapters[-1].seconds += seconds
            else:
                chapters.append(_Chapter(mood, seconds))
            divider_before = clip.has_transition_after
        return chapters

    @classmethod
    def from_clips(
        cls,
        clips: list[tuple[float, str, int | None]],  # List of (duration, mood, month)
        transitions_after: list[int] | None = None,  # Indices with transitions after
        title_duration: float = 3.5,
        ending_duration: float = 4.0,
        transition_duration: float = 2.0,
        fade_buffer: float = 5.0,
    ) -> VideoTimeline:
        """Create timeline from clip list.

        Args:
            clips: List of (duration, mood, month) tuples. Month can be None.
            transitions_after: Indices of clips that have transitions after them
            title_duration: Title screen duration
            ending_duration: Ending screen duration
            transition_duration: Duration of each transition
            fade_buffer: Extra buffer for fade out

        Returns:
            VideoTimeline instance
        """
        transitions_after = transitions_after or []

        clip_moods = []
        for i, clip_data in enumerate(clips):
            # Support both (duration, mood) and (duration, mood, month) tuples
            if len(clip_data) == 2:
                duration, mood = clip_data
                month = None
            else:
                duration, mood, month = clip_data

            clip_moods.append(
                ClipMood(
                    duration=duration,
                    mood=mood,
                    has_transition_after=(i in transitions_after),
                    transition_duration=transition_duration,
                    month=month,
                )
            )

        return cls(
            title_duration=title_duration,
            ending_duration=ending_duration,
            fade_buffer=fade_buffer,
            clips=clip_moods,
        )


def _scene_mood(clip: ClipMood, hemisphere: str) -> str:
    """The clip's mood, lifted for a memory film and coloured by its season."""
    mood = _transform_mood(clip.mood)
    if clip.month:
        seasonal = get_seasonal_prompt(clip.month, hemisphere)
        if seasonal:
            mood = f"{mood}, {seasonal}"
    return mood


def _merge_short_chapters(chapters: list[_Chapter]) -> list[_Chapter]:
    """Fold chapters too short to be a section, then the shortest, into a neighbour.

    The service caps the scene count; a chapter split for length needs room too.
    """
    budget = _MAX_SCENES - math.ceil(sum(c.seconds for c in chapters) / _SCENE_MAX_SECONDS)
    while len(chapters) > 1:
        lengths = [chapter.seconds for chapter in chapters]
        shortest = min(range(len(chapters)), key=lengths.__getitem__)
        if lengths[shortest] >= _MIN_CHAPTER_SECONDS and len(chapters) <= max(budget, 1):
            break
        into = shortest - 1 if shortest > 0 else 1
        chapters[into].seconds += chapters[shortest].seconds
        del chapters[shortest]
    return chapters


def _whole_second_scenes(scenes: list[tuple[str, float]], total: int) -> list[dict]:
    """Whole-second scenes of at least the service minimum, summing to ``total``."""
    durations = [max(_SCENE_MIN_SECONDS, round(seconds)) for _mood, seconds in scenes]
    durations[-1] = max(_SCENE_MIN_SECONDS, durations[-1] + total - sum(durations))
    return [
        {"mood": mood, "duration": duration}
        for (mood, _seconds), duration in zip(scenes, durations, strict=True)
    ]


def _transform_mood(mood: str) -> str:
    """Transform mood to be more upbeat for memory videos.

    Memory videos should feel upbeat and fun, not slow and sad.

    Args:
        mood: Original mood string

    Returns:
        Transformed mood string
    """
    mood_lower = mood.lower()
    mellow_words = [
        "calm",
        "peaceful",
        "serene",
        "gentle",
        "soft",
        "quiet",
        "slow",
        "relaxed",
        "mellow",
        "tender",
    ]
    sad_words = [
        "sad",
        "melancholy",
        "somber",
        "nostalgic",
        "reflective",
        "wistful",
        "bittersweet",
    ]

    if any(word in mood_lower for word in mellow_words):
        # Replace mellow with energetic but warm
        return f"upbeat warm groovy {mood}"
    elif any(word in mood_lower for word in sad_words):
        # Boost with warm positive words but keep original for template matching
        return f"warm hopeful {mood}"
    else:
        # For all other moods, ensure they're upbeat
        if "upbeat" not in mood_lower and "energetic" not in mood_lower:
            return f"upbeat {mood}"
    return mood


@dataclass
class MusicStems:
    """Separated audio stems from Demucs.

    Supports both 2-stem (vocals/accompaniment) and 4-stem (drums/bass/vocals/other)
    separation modes. Use `has_full_stems` to check which mode was used.
    """

    vocals: Path  # Melody/vocal stem (duck most aggressively)
    accompaniment: Path | None = None  # Combined drums+bass+other (2-stem mode)

    # 4-stem mode (htdemucs) - more granular control
    drums: Path | None = None  # Drum stem (duck least)
    bass: Path | None = None  # Bass stem (duck moderately)
    other: Path | None = None  # Other instruments (duck moderately)

    @property
    def has_full_stems(self) -> bool:
        """Check if 4-stem separation was used."""
        return self.drums is not None and self.bass is not None

    def cleanup(self):
        """Remove stem files."""
        for path in (self.vocals, self.accompaniment, self.drums, self.bass, self.other):
            if path and path.exists():
                path.unlink()


@dataclass
class GeneratedMusic:
    """A single generated music version."""

    full_mix: Path
    stems: MusicStems | None = None
    duration: float = 0.0
    prompt: str = ""
    mood: str = ""

    def cleanup(self):
        """Remove all associated files."""
        if self.full_mix.exists():
            self.full_mix.unlink()
        if self.stems:
            self.stems.cleanup()


@dataclass
class MusicGenerationResult:
    """Result containing multiple versions for user selection."""

    versions: list[GeneratedMusic]
    timeline: VideoTimeline
    mood: str
    selected_version: int | None = None  # User's choice (0-indexed)

    @property
    def selected(self) -> GeneratedMusic | None:
        """Get the selected version."""
        if self.selected_version is not None and 0 <= self.selected_version < len(self.versions):
            return self.versions[self.selected_version]
        return None

    def cleanup_unselected(self):
        """Remove unselected versions to save space."""
        for i, version in enumerate(self.versions):
            if i != self.selected_version:
                version.cleanup()
