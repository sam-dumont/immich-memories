"""Bundled royalty-free music, used when no generation backend is available.

The tracks ship in the separate ``immich-memories-music`` distribution (the
``music`` extra) so a plain install stays small, while the Docker image — which
installs every extra — has music without a GPU or a music server.
"""

from __future__ import annotations

import logging
import math
import random
from pathlib import Path

from immich_memories.audio.mixer import get_audio_duration

logger = logging.getLogger(__name__)

_SUFFIXES = (".opus", ".mp3", ".m4a", ".flac", ".ogg", ".wav")

# The package ships five folders; the analyser's mood families are wider than
# that. A near neighbour is better music for the memory than the flat pool, so
# the families with no folder of their own borrow the closest one that has.
_MOOD_FOLDERS = {
    "playful": "happy",
    "peaceful": "calm",
    "exciting": "energetic",
    "romantic": "tender",
}


def bundled_library() -> Path | None:
    """Directory of bundled tracks, or None when the music package is absent."""
    try:
        from immich_memories_music import tracks_dir
    except ImportError:
        return None
    directory = tracks_dir()
    return directory if directory.is_dir() else None


def bundled_track_for_mood(
    mood: str | None,
    library: Path | None = None,
    cadence_seconds: float | None = None,
) -> Path | None:
    """Pick a bundled track for a mood, at random so repeats differ.

    Falls back to any bundled track when the mood has no folder of its own: some
    music beats silence, and the analyser's mood vocabulary is wider than the set
    of moods we ship.

    With a photo cadence, the pick stops being random and becomes the track whose
    beat divides that cadence -- the bundled counterpart to asking a generator
    for a beat-aligned tempo (#312). Without photos there is no rhythm to sync
    to, so variety wins and the choice stays random.
    """
    root = library if library is not None else bundled_library()
    if root is None or not root.is_dir():
        return None

    candidates = _mood_candidates(mood, root)
    if not candidates:
        return None

    chosen = _fitting_track(candidates, cadence_seconds) or random.choice(candidates)
    logger.info("Using bundled music: %s/%s", chosen.parent.name, chosen.name)
    return chosen


def bundled_playlist_for_mood(
    mood: str | None,
    total_duration: float,
    library: Path | None = None,
    cadence_seconds: float | None = None,
    seed: int | None = None,
) -> list[Path]:
    """Order several mood-matched bundled tracks to cover ``total_duration``.

    A long film used to loop one ~30 s bundled track up to 20 times (#2070):
    one short phrase, repeated, for the whole runtime. This instead walks the
    mood's pool picking a track at random each step, excluding whichever
    track was just used whenever the pool has another to offer, until the
    picks add up to the target length. ``assemble_music`` (mixer.py) then
    crossfades the sequence into one track.

    Returns a single-entry list when one candidate is already long enough —
    the short-film case is unaffected by this — and an empty list when there
    is no bundled library to draw from.
    """
    root = library if library is not None else bundled_library()
    if root is None or not root.is_dir():
        return []

    candidates = _mood_candidates(mood, root)
    if not candidates:
        return []

    durations = {track: get_audio_duration(track) for track in candidates}
    if sum(durations.values()) <= 0:
        # Every candidate's duration is unreadable (corrupt or a test fixture
        # with no real audio) — degrade to a single random pick rather than
        # spin the covering loop below forever on zero-length steps.
        logger.warning("Bundled tracks for %r have no readable duration", mood)
        return [random.Random(seed).choice(candidates)]

    fitting = _fitting_track(candidates, cadence_seconds)
    if fitting is not None and durations[fitting] >= total_duration:
        return [fitting]

    longest = max(candidates, key=lambda track: durations[track])
    if durations[longest] >= total_duration:
        return [longest]

    return _covering_playlist(candidates, durations, total_duration, seed)


def _covering_playlist(
    candidates: list[Path],
    durations: dict[Path, float],
    total_duration: float,
    seed: int | None,
) -> list[Path]:
    """Random walk over ``candidates``, no back-to-back repeat when avoidable."""
    rng = random.Random(seed)
    longest_duration = max(durations.values())
    # A finite bound even if every pick landed on the pool's shortest track.
    max_picks = max(4, math.ceil(total_duration / max(longest_duration, 0.1)) * 4)

    playlist: list[Path] = []
    covered = 0.0
    previous: Path | None = None
    while covered < total_duration and len(playlist) < max_picks:
        choices = [track for track in candidates if track != previous] or candidates
        track = rng.choice(choices)
        playlist.append(track)
        covered += durations[track]
        previous = track
    return playlist


def _mood_candidates(mood: str | None, root: Path) -> list[Path]:
    """Tracks in the mood's own folder, or the whole library when it has none."""
    family = (mood or "").lower()
    folder = root / _MOOD_FOLDERS.get(family, family)
    candidates = _tracks_in(folder) if folder.is_dir() else []
    if not candidates:
        candidates = sorted(
            track for child in root.iterdir() if child.is_dir() for track in _tracks_in(child)
        )
    return candidates


def _tracks_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in _SUFFIXES)


def _fitting_track(candidates: list[Path], cadence_seconds: float | None) -> Path | None:
    """The candidate whose beat lands on the cadence, when there is one to land on."""
    if not cadence_seconds:
        return None
    from immich_memories.audio.track_tempo import track_for_cadence

    return track_for_cadence(candidates, cadence_seconds)
