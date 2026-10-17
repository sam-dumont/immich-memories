"""Bundled royalty-free music, used when no generation backend is available.

The music-v2 library (``models fetch``, built into the Docker image) plays when it
is installed. Otherwise the older tracks of the separate ``immich-memories-music``
distribution (the ``music`` extra) do, so a plain install stays small and the
Docker image has music without a GPU or a music server.

Your own folder (``audio.local_music_dir``), laid out the same way, takes the
bundle's place for every mood it has a folder for.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

from immich_memories.audio.mood_analyzer import MOOD_FOLDERS

logger = logging.getLogger(__name__)

_SUFFIXES = (".opus", ".mp3", ".m4a", ".flac", ".ogg", ".wav")

# The package ships five folders; the analyser's mood families are wider than
# that. A near neighbour is better music for the memory than the flat pool, so
# the families with no folder of their own borrow the closest one that has.


def bundled_library() -> Path | None:
    """Directory of bundled tracks: the music-v2 library when installed, else the 0.1.0 package.

    Reads the disk only. A film never downloads music; ``models fetch`` and the
    image build put music-v2 in place ahead of time.
    """
    from immich_memories.music_library import installed_music_v2

    installed = installed_music_v2()
    if installed is not None:
        return installed
    try:
        from immich_memories_music import tracks_dir
    except ImportError:
        logger.info("music-v2 is not installed and the music package is absent; no bundled music")
        return None
    directory = tracks_dir()
    if not directory.is_dir():
        return None
    logger.info("music-v2 is not installed; using the 0.1.0 tracks (run `models fetch`)")
    return directory


def music_library_for_mood(
    mood: str | None,
    own_library: Path | None,
    bundled: Path | None,
    *,
    own_library_named: bool = True,
) -> Path | None:
    """The library a film of this mood picks its music from: your folder, else the bundle.

    Your folder wins for every mood it has tracks for. A mood it lacks plays the
    bundled tracks for that mood; a mood neither has a folder for picks from all
    of your folder, since any track of yours is closer to what you want than any
    bundled one. The log names the mood, never the folder: the path comes from
    the config.
    """
    family = (mood or "").lower()
    if own_library is None or not _all_tracks(own_library):
        # The default folder rarely exists; only a folder someone named is worth a warning.
        log = logger.warning if own_library_named else logger.debug
        log("Your music folder is missing or has no tracks; films use the bundled music")
        return bundled
    if not family or _mood_folder_tracks(family, own_library):
        logger.info("Picking %s music from your music folder", family or "any")
        return own_library
    if bundled is not None and bundled.is_dir() and _mood_folder_tracks(family, bundled):
        logger.info("Your music folder has no %s tracks; using the bundled ones", family)
        return bundled
    # Neither library has the mood: any track of yours is closer to what you want.
    logger.info("No library has %s tracks; picking from all of your music folder", family)
    return own_library


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
    logger.info("Using music track: %s/%s", chosen.parent.name, chosen.name)
    return chosen


def _mood_candidates(mood: str | None, root: Path) -> list[Path]:
    """Tracks in the mood's own folder, or the whole library when it has none."""
    return _mood_folder_tracks((mood or "").lower(), root) or _all_tracks(root)


def _mood_folder_tracks(family: str, root: Path) -> list[Path]:
    """The tracks of a mood's folder: its own name first, then the near neighbour's.

    The bundle has no folder for some moods; a library of your own may.
    """
    for name in dict.fromkeys((family, MOOD_FOLDERS.get(family, family))):
        folder = root / name
        tracks = _tracks_in(folder) if folder.is_dir() else []
        if tracks:
            return tracks
    return []


def library_has_tracks(root: Path | None) -> bool:
    """Whether a music library holds at least one track in a mood folder."""
    return root is not None and bool(_all_tracks(root))


def _all_tracks(root: Path) -> list[Path]:
    """Every track in the library's mood folders."""
    if not root.is_dir():
        return []
    return sorted(
        track for child in root.iterdir() if child.is_dir() for track in _tracks_in(child)
    )


def _tracks_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES)


def _fitting_track(candidates: list[Path], cadence_seconds: float | None) -> Path | None:
    """The candidate whose beat lands on the cadence, when there is one to land on."""
    if not cadence_seconds:
        return None
    from immich_memories.audio.track_tempo import track_for_cadence

    return track_for_cadence(candidates, cadence_seconds)
