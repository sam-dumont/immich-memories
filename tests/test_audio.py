"""Tests for audio module."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.audio.mixer import (
    DuckingConfig,
    MixConfig,
)
from immich_memories.audio.mood_analyzer import VideoMood
from immich_memories.audio.music_sources import (
    LocalMusicSource,
    MusicTrack,
)


class TestMusicTrack:
    """Tests for MusicTrack class."""

    def test_basic_track(self):
        """Test basic track creation."""
        track = MusicTrack(
            id="123",
            title="Test Song",
            artist="Test Artist",
            duration_seconds=180.0,
            url="https://example.com/song.mp3",
        )
        assert track.id == "123"
        assert track.title == "Test Song"
        assert track.artist == "Test Artist"
        assert track.duration_seconds == 180.0


class TestDuckingConfig:
    """Tests for DuckingConfig class."""

    def test_custom_values(self):
        """Test custom ducking configuration."""
        config = DuckingConfig(
            threshold=0.05,
            ratio=8.0,
            music_volume_db=-12.0,
        )
        assert config.threshold == 0.05
        assert config.ratio == 8.0
        assert config.music_volume_db == -12.0


class TestMixConfig:
    """Tests for MixConfig class."""

    def test_custom_values(self):
        """Test custom mix configuration."""
        config = MixConfig(
            ducking=DuckingConfig(),
            fade_in_seconds=1.0,
            fade_out_seconds=2.0,
            normalize_audio=False,
        )
        assert config.fade_in_seconds == 1.0
        assert config.fade_out_seconds == 2.0
        assert not config.normalize_audio


class TestVideoMood:
    """Tests for VideoMood class."""

    def test_basic_mood(self):
        """Test basic mood creation."""
        mood = VideoMood(
            primary_mood="happy",
            energy_level="high",
            tempo_suggestion="fast",
        )
        assert mood.primary_mood == "happy"
        assert mood.energy_level == "high"
        assert mood.tempo_suggestion == "fast"


class TestLocalMusicSource:
    """Tests for LocalMusicSource class."""

    def test_supported_extensions(self):
        """Test supported extensions are defined."""
        assert ".mp3" in LocalMusicSource.SUPPORTED_EXTENSIONS
        assert ".m4a" in LocalMusicSource.SUPPORTED_EXTENSIONS
        assert ".wav" in LocalMusicSource.SUPPORTED_EXTENSIONS

    def test_nonexistent_directory(self):
        """Test handling of nonexistent directory."""
        source = LocalMusicSource(Path("/nonexistent/path"))
        tracks = source._scan_directory()
        assert not tracks

    @pytest.mark.asyncio
    async def test_search_empty(self):
        """Test search on empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = LocalMusicSource(Path(tmpdir))
            tracks = await source.search()
            assert not tracks

    @pytest.mark.asyncio
    async def test_download_existing(self):
        """Test download returns local path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.mp3"
            test_file.write_bytes(b"test content")

            track = MusicTrack(
                id="test",
                title="Test",
                artist="Artist",
                duration_seconds=60,
                url=f"file://{test_file}",
                local_path=test_file,
            )

            source = LocalMusicSource(Path(tmpdir))
            result = await source.download(track, Path(tmpdir))
            assert result == test_file


def _tagged_track(path: Path, *, seconds: float, title: str | None, artist: str | None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tags: list[str] = []
    if title is not None:
        tags += ["-metadata", f"title={title}"]
    if artist is not None:
        tags += ["-metadata", f"artist={artist}"]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
        ]
        + tags
        + [str(path)],
        check=True,
    )
    return path


class TestLocalMusicMetadata:
    """Track metadata comes from the file's own tags, read with ffprobe (#1890)."""

    @pytest.mark.parametrize("suffix", [".mp3", ".m4a", ".flac", ".opus"])
    def test_title_artist_and_duration_come_from_the_tags(self, tmp_path, suffix):
        _tagged_track(
            tmp_path / f"song{suffix}", seconds=2.0, title="Golden Hour", artist="Kacey M"
        )

        (track,) = LocalMusicSource(tmp_path).tracks

        assert (track.title, track.artist) == ("Golden Hour", "Kacey M")
        assert track.duration_seconds == pytest.approx(2.0, abs=0.1)

    def test_an_untagged_file_falls_back_to_its_name(self, tmp_path):
        _tagged_track(tmp_path / "calm" / "morning walk.flac", seconds=1.0, title=None, artist=None)

        (track,) = LocalMusicSource(tmp_path).tracks

        assert (track.title, track.artist) == ("morning walk", "Unknown")
        assert track.duration_seconds == pytest.approx(1.0, abs=0.1)
        assert "calm" in track.tags

    def test_an_unreadable_file_is_still_listed_with_no_duration(self, tmp_path):
        (tmp_path / "broken.mp3").write_bytes(b"not audio")

        (track,) = LocalMusicSource(tmp_path).tracks

        assert (track.title, track.artist, track.duration_seconds) == ("broken", "Unknown", 0.0)


class TestMusicTrackEdgeCases:
    """Edge cases for MusicTrack."""

    def test_zero_duration_track(self):
        """Track with zero duration is valid."""
        track = MusicTrack(
            id="1",
            title="T",
            artist="A",
            duration_seconds=0.0,
            url="https://example.com/song.mp3",
        )
        assert track.duration_seconds == 0.0


class TestBundledMoodFolders:
    """A mood folder is only usable if its name is recognised as a tag (#308)."""

    def test_every_mood_the_analyser_can_return_is_matchable_by_folder(self, tmp_path):
        from immich_memories.audio.mood_analyzer import VALID_MOODS
        from immich_memories.audio.music_sources import LocalMusicSource

        unmatched = sorted(
            mood
            for mood in VALID_MOODS
            if mood not in LocalMusicSource._extract_tags_from_path(tmp_path / mood / "x.mp3", "x")
        )

        assert unmatched == []

    def test_opus_tracks_are_discoverable(self, tmp_path):
        """Bundled music ships as Opus; an unlisted extension is silently ignored (#308)."""
        from immich_memories.audio.music_sources import LocalMusicSource

        assert ".opus" in LocalMusicSource.SUPPORTED_EXTENSIONS


class TestMusicStepsAsideForSourceMusic:
    """#466: when a clip's own audio IS music, the soundtrack must step
    aside for that clip's window — sidechain compression only lowers it,
    and two songs at once is what the matrix review heard."""

    def test_mute_windows_reach_the_music_filter(self):
        from immich_memories.audio.mixer import _build_ducking_filter

        config = MixConfig(ducking=DuckingConfig(), mute_windows=[(10.0, 14.5)])

        parts = _build_ducking_filter(config, config.ducking, video_duration=30.0)
        music_chain = next(p for p in parts if p.startswith("[1:a]"))

        assert "between(t,10.0,14.5)" in music_chain
        assert "volume=" in music_chain

    def test_no_windows_means_the_chain_is_unchanged(self):
        from immich_memories.audio.mixer import _build_ducking_filter

        config = MixConfig(ducking=DuckingConfig())

        parts = _build_ducking_filter(config, config.ducking, video_duration=30.0)
        music_chain = next(p for p in parts if p.startswith("[1:a]"))

        assert "between(" not in music_chain


class TestMusicMuteWindows:
    """Timeline windows of clips whose source audio is music."""

    def _clip(self, duration: float, has_music: bool = False):
        from pathlib import Path

        from immich_memories.processing.assembly_config import AssemblyClip

        return AssemblyClip(
            path=Path("/x.mp4"), duration=duration, asset_id="x", has_music=has_music
        )

    def test_windows_follow_the_timeline_with_crossfade_overlap(self):
        from immich_memories.audio.mixer import music_mute_windows

        clips = [self._clip(10.0), self._clip(8.0, has_music=True), self._clip(6.0)]

        windows = music_mute_windows(clips, ["fade", "cut"], fade_duration=1.0)

        # clip B starts at 10 - 1 (crossfade overlap) = 9.0, runs 8s
        assert windows == [(9.0, 17.0)]

    def test_adjacent_music_clips_merge_into_one_window(self):
        from immich_memories.audio.mixer import music_mute_windows

        clips = [self._clip(10.0, has_music=True), self._clip(8.0, has_music=True)]

        windows = music_mute_windows(clips, ["cut"], fade_duration=1.0)

        assert windows == [(0.0, 18.0)]

    def test_music_window_stays_with_its_clip_after_fractional_frame_trims(self):
        from immich_memories.audio.mixer import music_mute_windows

        clips = [self._clip(1.029) for _ in range(20)]
        clips.append(self._clip(1.029, has_music=True))

        windows = music_mute_windows(clips, ["fade"] * 20, fade_duration=0.5)

        # At the assembler's default 30 fps, each clip contributes 30 frames,
        # and each overlap consumes 15. Music starts with frame 300, not 317.
        assert windows == [(10.0, 11.0)]

    def test_no_music_no_windows(self):
        from immich_memories.audio.mixer import music_mute_windows

        assert music_mute_windows([self._clip(10.0)], [], fade_duration=1.0) == []


class TestMuteWindowWiring:
    def test_apply_music_file_hands_windows_to_the_mixer(self, tmp_path):

        from immich_memories.generate_music import apply_music_file

        captured = {}

        # WHY: mixing runs real ffmpeg; the contract here is config plumbing
        def spy(video_path, music_path, output_path, config):
            captured["windows"] = config.mute_windows
            raise RuntimeError("stop after capture")

        # WHY: mixing runs real ffmpeg and staging touches the filesystem
        with (
            patch("immich_memories.audio.mixer.mix_audio_with_ducking", side_effect=spy),
            patch("immich_memories.generate_music.staged_music_output"),
        ):
            try:
                apply_music_file(
                    tmp_path / "v.mp4",
                    tmp_path / "m.mp3",
                    0.5,
                    MagicMock(),
                    mute_windows=[(3.0, 9.0)],
                )
            except Exception:
                pass

        assert captured["windows"] == [(3.0, 9.0)]
