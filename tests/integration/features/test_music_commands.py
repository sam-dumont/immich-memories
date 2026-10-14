"""The standalone music commands: `music search` over the local library, `music add` under a video.

The real CLI runs in a sealed home whose `~/Music/Memories` holds tracks FFmpeg drew for the
test. What is checked is what a user gets: the tracks listed, and the mixed file's sound,
measured band by band (the music is a 300 Hz tone, the video's own sound a 2 kHz one).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.features.cli_harness import UserHome, basic_config, film_facts

UNREACHABLE = "http://127.0.0.1:9"  # discard port: these commands never ask Immich


def _ffmpeg(*args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True
    )


def _track(path: Path, seconds: float, *, genre: str | None = None, hz: int = 300) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = ["-metadata", f"genre={genre}"] if genre else []
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", *tags, str(path))
    return path


@pytest.fixture
def home(tmp_path: Path) -> UserHome:
    home = UserHome(tmp_path / "home")
    home.write_config(basic_config(UNREACHABLE, "a-key", home))
    return home


# ── music search ─────────────────────────────────────────────────────────────


def _titles(home: UserHome, *args: str) -> list[str]:
    result = home.run("music", "search", *args)
    assert result.returncode == 0, result.explain()
    return sorted(re.findall(r"│ (track-[a-z-]+)\s", result.stdout))


@pytest.mark.feature("music.search")
def test_music_search_finds_local_tracks_by_mood_genre_tempo_and_length(home: UserHome):
    library = home.root / "Music" / "Memories"
    _track(library / "calm" / "slow" / "track-harbour-morning.flac", 90, genre="Acoustic")
    _track(library / "energetic" / "fast" / "track-night-drive.flac", 120, genre="Electronic")
    _track(library / "calm" / "fast" / "track-short-run.flac", 30, genre="Acoustic")

    # Length: the 30-second track is under the default minute.
    assert _titles(home, "--mood", "calm") == ["track-harbour-morning"]
    assert _titles(home, "--mood", "calm", "--min-duration", "20") == [
        "track-harbour-morning",
        "track-short-run",
    ]
    assert _titles(home, "--genre", "electronic") == ["track-night-drive"]
    assert _titles(home, "--tempo", "fast", "--min-duration", "20") == [
        "track-night-drive",
        "track-short-run",
    ]
    assert _titles(home, "--genre", "acoustic", "--tempo", "slow") == ["track-harbour-morning"]
    assert len(_titles(home, "--min-duration", "20", "--limit", "2")) == 2


# ── music add ────────────────────────────────────────────────────────────────

# The video's own sound plays from 4 s to 6 s of a 12-second clip; elsewhere it is silent.
_VOICE = "4", "6"
_SECONDS = 12


def _video_with_a_voice(path: Path) -> Path:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x240:rate=25:duration={_SECONDS}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=2000:duration={_SECONDS}",
        "-af",
        f"volume='if(between(t,{_VOICE[0]},{_VOICE[1]}),0.8,0)':eval=frame",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    )
    return path


def _music_db(film: Path, start: float, seconds: float) -> float:
    """Mean level of the 300 Hz music band over [start, start + seconds), in dB."""
    detected = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "info",
            "-ss",
            f"{start}",
            "-t",
            f"{seconds}",
            "-i",
            str(film),
            "-vn",
            "-af",
            "bandpass=f=300:width_type=h:w=80,bandpass=f=300:width_type=h:w=80,volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    mean = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", detected)
    assert mean, detected[-2000:]
    return -91.0 if mean.group(1) == "-inf" else float(mean.group(1))


def _add(home: UserHome, video: Path, music: Path, out: Path, volume: str) -> None:
    result = home.run(
        "music",
        "add",
        str(video),
        str(out),
        "--music",
        str(music),
        "--volume",
        volume,
        "--fade-in",
        "2",
        "--fade-out",
        "2",
    )
    assert result.returncode == 0, result.explain()
    assert f"Video saved to: {out}" in result.stdout.replace("\n", ""), result.explain()


@pytest.mark.feature("music.add")
def test_music_add_mixes_a_track_under_a_video_ducked_faded_and_at_the_given_volume(
    home: UserHome, tmp_path: Path
):
    video = _video_with_a_voice(tmp_path / "clip.mp4")
    music = _track(tmp_path / "song.wav", 30)
    loud, quiet = tmp_path / "loud.mp4", tmp_path / "quiet.mp4"

    _add(home, video, music, loud, "-6")
    _add(home, video, music, quiet, "-18")

    facts = film_facts(loud)
    assert facts.has_audio
    assert facts.duration == pytest.approx(_SECONDS, abs=0.2)
    assert (facts.width, facts.height, facts.codec) == (320, 240, "h264")
    steady = _music_db(loud, 2.5, 1.2)
    # The music is there, and the video's own sound still plays over it.
    assert steady > -40
    # It fades in and out rather than starting and stopping at full level.
    assert _music_db(loud, 0.0, 0.3) < steady - 6
    assert _music_db(loud, _SECONDS - 0.3, 0.3) < steady - 6
    # It ducks under the video's own sound, then comes back once that has stopped.
    assert _music_db(loud, 4.6, 1.2) < steady - 3
    assert _music_db(loud, 9.0, 0.8) > steady - 2
    # --volume sets the music's level: 12 dB down is 12 dB down.
    assert _music_db(quiet, 2.5, 1.2) == pytest.approx(steady - 12, abs=2)
