"""Music source providers for automatic background music."""

from __future__ import annotations

import json
import logging
import random
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MusicTrack:
    """Represents a music track."""

    id: str
    title: str
    artist: str
    duration_seconds: float
    url: str
    tags: list[str] = field(default_factory=list)
    mood: str | None = None
    genre: str | None = None
    tempo: str | None = None  # "slow", "medium", "fast"
    source: str = "unknown"
    local_path: Path | None = None


class MusicSource(ABC):
    """Abstract base class for music sources."""

    @abstractmethod
    async def search(
        self,
        mood: str | None = None,
        genre: str | None = None,
        tempo: str | None = None,
        min_duration: float = 60,
        max_duration: float = 600,
        limit: int = 10,
    ) -> list[MusicTrack]:
        """Search for music tracks.

        Args:
            mood: Mood/feeling (e.g., "happy", "calm", "energetic")
            genre: Music genre (e.g., "acoustic", "electronic", "cinematic")
            tempo: Tempo preference ("slow", "medium", "fast")
            min_duration: Minimum duration in seconds
            max_duration: Maximum duration in seconds
            limit: Maximum number of results

        Returns:
            List of matching MusicTrack objects
        """
        pass

    @abstractmethod
    async def download(
        self,
        track: MusicTrack,
        output_dir: Path,
    ) -> Path:
        """Download a track to local storage.

        Args:
            track: The track to download
            output_dir: Directory to save the file

        Returns:
            Path to the downloaded file
        """
        pass

    async def get_random_track(
        self,
        mood: str | None = None,
        genre: str | None = None,
        tempo: str | None = None,
        min_duration: float = 60,
    ) -> MusicTrack | None:
        """Get a random track matching criteria.

        Args:
            mood: Mood/feeling preference
            genre: Genre preference
            tempo: Tempo preference
            min_duration: Minimum duration

        Returns:
            A random matching track, or None if no matches
        """
        tracks = await self.search(
            mood=mood,
            genre=genre,
            tempo=tempo,
            min_duration=min_duration,
            limit=20,
        )
        return random.choice(tracks) if tracks else None


class LocalMusicSource(MusicSource):
    """Local music library source.

    Scans a directory for music files and provides search functionality.
    """

    SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus"}

    def __init__(self, music_dir: Path):
        """Initialize with a local music directory.

        Args:
            music_dir: Directory containing music files
        """
        self.music_dir = Path(music_dir)
        self._tracks: list[MusicTrack] | None = None

    @staticmethod
    def _read_tag_metadata(path: Path) -> tuple[float, str, str, str | None]:
        """Read duration, title, artist and genre with ffprobe.

        Tags live on the container for MP3/M4A/FLAC but on the audio stream for
        Ogg and Opus, and their keys can be upper case (Vorbis comments), so
        both blocks are merged and keys are lowered.
        """
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:format_tags:stream_tags",
                "-of",
                "json",
                str(path.absolute()),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        probe = json.loads(result.stdout)
        tags: dict[str, str] = {}
        for block in (*probe.get("streams", []), probe.get("format", {})):
            tags |= {key.lower(): value for key, value in block.get("tags", {}).items()}
        duration = float(probe.get("format", {}).get("duration") or 0.0)
        title, artist = tags.get("title") or path.stem, tags.get("artist") or "Unknown"
        return duration, title, artist, tags.get("genre") or None

    @staticmethod
    def _extract_tags_from_path(path: Path, title: str) -> list[str]:
        """Infer mood tags from parent directory name and title.

        Uses the analyser's own vocabulary so any mood it can return is also a
        usable folder name — bundled music ships one folder per mood.
        """
        from immich_memories.audio.mood_analyzer import VALID_MOODS

        parent_name = path.parent.name.lower()
        title_lower = title.lower()
        return sorted(mood for mood in VALID_MOODS if mood in parent_name or mood in title_lower)

    def _load_track_metadata(self, path: Path) -> tuple[float, str, str, str | None]:
        """Load duration, title, artist, genre — falls back to filename on error."""
        try:
            return self._read_tag_metadata(path)
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0.0, path.stem, "Unknown", None

    def _scan_directory(self) -> list[MusicTrack]:
        """Scan directory for music files."""
        if not self.music_dir.exists():
            logger.warning(f"Music directory does not exist: {self.music_dir}")
            return []

        tracks: list[MusicTrack] = []
        for path in self.music_dir.rglob("*"):
            if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue
            duration, title, artist, genre = self._load_track_metadata(path)
            tags = self._extract_tags_from_path(path, title)
            tracks.append(
                MusicTrack(
                    id=str(path),
                    title=title,
                    artist=artist,
                    duration_seconds=duration,
                    url=f"file://{path}",
                    tags=tags,
                    genre=genre,
                    source="local",
                    local_path=path,
                )
            )
        return tracks

    @property
    def tracks(self) -> list[MusicTrack]:
        """Get all tracks (cached)."""
        if self._tracks is None:
            self._tracks = self._scan_directory()
        return self._tracks

    @staticmethod
    def _track_matches_duration(
        track: MusicTrack, min_duration: float, max_duration: float
    ) -> bool:
        """Return False if track duration is known and outside bounds."""
        if track.duration_seconds <= 0:
            return True
        return min_duration <= track.duration_seconds <= max_duration

    def _track_matches_term(self, track: MusicTrack, term: str) -> bool:
        """Whether term appears in the track's tags, title, artist, genre tag or folders.

        A library is sorted the way its owner sorts it: `Memories/acoustic/slow/x.mp3`
        answers `--genre acoustic` and `--tempo slow` as much as a genre tag does.
        """
        folders: tuple[str, ...] = ()
        if track.local_path is not None and track.local_path.is_relative_to(self.music_dir):
            folders = track.local_path.relative_to(self.music_dir).parts[:-1]
        words = [*track.tags, track.title, track.artist, track.genre or "", *folders]
        term_lower = term.lower()
        return any(term_lower in word.lower() for word in words)

    async def search(
        self,
        mood: str | None = None,
        genre: str | None = None,
        tempo: str | None = None,
        min_duration: float = 60,
        max_duration: float = 600,
        limit: int = 10,
    ) -> list[MusicTrack]:
        """Search local music library."""
        results = []
        for track in self.tracks:
            if not self._track_matches_duration(track, min_duration, max_duration):
                continue
            if mood and not self._track_matches_term(track, mood):
                continue
            if genre and not self._track_matches_term(track, genre):
                continue
            if tempo and not self._track_matches_term(track, tempo):
                continue
            results.append(track)
            if len(results) >= limit:
                break
        return results

    async def download(
        self,
        track: MusicTrack,
        output_dir: Path,
    ) -> Path:
        """Return local path (no download needed)."""
        if track.local_path and track.local_path.exists():
            return track.local_path
        raise ValueError(f"Local track not found: {track.id}")
