"""Privacy mode in the encoded film, what the app sends Immich, and what leaves the network.

The privacy film is the fixture garden day rendered with --privacy-mode, each clip carrying
a voice-band stand-in on its soundtrack (the library's own clips are silent). Its frames
are compared with the session's plain garden film, the same cut at the same seconds.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.features.cli_harness import OutboundTrap, UserHome, basic_config, film_facts
from tests.integration.features.library import (
    GARDEN_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    render,
    shipped_on,
)

# Low enough to survive the privacy murmur, and well into the band consonants live in.
_VOICE_LOW_HZ, _VOICE_HIGH_HZ = 150, 1500
_SHOT = re.compile(r"^\s+(\d+):(\d\d)\s+\d{4}-\d\d-\d\d\s+(?:photo|video)\s+([\d.]+) s", re.M)
# Search reads are POSTs; nothing else the app sends Immich with upload off may write.
_READ_ONLY_POSTS = frozenset({"/api/search/metadata", "/api/search/statistics"})


def _with_a_voice(clip: Path, seconds: float, into: Path) -> Path:
    """The same clip, its silent track replaced by two tones in the speech band."""
    _ffmpeg(
        "-i",
        str(clip),
        "-f",
        "lavfi",
        "-i",
        f"sine=f={_VOICE_LOW_HZ}:d={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=f={_VOICE_HIGH_HZ}:d={seconds}",
        "-filter_complex",
        "[1:a][2:a]amix=inputs=2,aformat=channel_layouts=stereo:sample_rates=48000[voice]",
        "-map",
        "0:v",
        "-map",
        "[voice]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(into),
    )
    return into


def _ffmpeg(*args: str) -> str:
    return subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, check=True
    ).stderr


def _level_db(film: Path, band: str) -> float:
    """RMS level of the film's soundtrack after `band` (an FFmpeg audio filter chain)."""
    printed = _ffmpeg(
        "-i",
        str(film),
        "-vn",
        "-af",
        f"{band}astats=metadata=0:measure_overall=RMS_level:measure_perchannel=0",
        "-f",
        "null",
        "-",
    )
    return float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", printed)[-1])


def _picture(film: Path, at_seconds: float, *, blur_sigma: float = 0) -> np.ndarray:
    """The picture area (caption bands cropped off) of one frame, as grey levels."""
    blur = f"gblur=sigma={blur_sigma}," if blur_sigma else ""
    raw = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            str(film),
            "-frames:v",
            "1",
            "-vf",
            f"{blur}crop=iw:ih*0.7:0:ih*0.15,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).astype(float)


def _shot_middles(home: UserHome, run_id: str) -> list[float]:
    story = home.run("runs", "story", run_id)
    assert story.returncode == 0, story.explain()
    shots = _SHOT.findall(story.stdout)
    assert shots, story.explain()
    return [int(m) * 60 + int(s) + float(length) / 2 for m, s, length in shots]


@dataclass(frozen=True, slots=True)
class PrivateFilm:
    home: UserHome
    plain: RenderedRun
    run: RenderedRun
    # The voiced clips both were cut from.
    sources: tuple[Path, ...]
    # What Immich was sent while the private film rendered: (method, path).
    requests: list[tuple[str, str]]


@pytest.fixture(scope="module")
def private_film(
    tmp_path_factory: pytest.TempPathFactory,
    fake_immich: FakeImmichServer,
    outbound_trap: OutboundTrap,
) -> PrivateFilm:
    """The garden day plain and with --privacy-mode, its clips carrying a voice.

    Both log at DEBUG, which prints each shot's FFmpeg decode command: the caption text
    the render drew onto the frames.
    """
    root = tmp_path_factory.mktemp("voiced")
    voiced = {
        picture.asset_id: _with_a_voice(
            fake_immich.original(picture.asset_id),
            picture.seconds,
            root / f"{picture.asset_id}.mp4",
        )
        for picture in shipped_on(GARDEN_DAY)
        if picture.is_video
    }
    assert voiced, "the garden day ships a clip"
    # Its own home: the library home's cache already holds the silent clips.
    home = UserHome(root / "home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(fake_immich.base_url, fake_immich.api_key, home))
    with fake_immich.serving(voiced):
        plain = render(home, "--verbose", *day_args(GARDEN_DAY))
        start = len(fake_immich.wire.requests)
        run = render(home, "--verbose", *day_args(GARDEN_DAY), "--privacy-mode")
        requests = fake_immich.wire.requests[start:]
    return PrivateFilm(home, plain, run, tuple(voiced.values()), requests)


def _drawn_places(run: RenderedRun) -> list[str]:
    """The place captions the render drew (top-left drawtext), in shot order."""
    return re.findall(r"drawtext=text='([^']*)'.*?:x=\d+:y=\d+", run.result.output)


@pytest.mark.feature("privacy.privacy-mode")
def test_privacy_mode_blurs_every_picture_in_the_encoded_film(private_film: PrivateFilm):
    middles = _shot_middles(private_film.home, private_film.plain.run_id)
    assert _shot_middles(private_film.home, private_film.run.run_id) == middles

    for at in middles:
        private = _picture(private_film.run.film, at)
        original = _picture(private_film.plain.film, at)
        blurred = _picture(private_film.plain.film, at, blur_sigma=14)
        to_original = float(((private - original) ** 2).mean())
        to_blurred = float(((private - blurred) ** 2).mean())
        # Every shot reads as a heavy blur of its picture, not as the picture.
        assert to_blurred * 4 < to_original, (at, to_blurred, to_original)


@pytest.mark.feature("privacy.privacy-mode")
def test_privacy_mode_moves_the_places_the_film_names(private_film: PrivateFilm):
    pictures = shipped_on(GARDEN_DAY)
    real = {p.place.city.upper() for p in pictures} | {p.place.country.upper() for p in pictures}

    plain, private = _drawn_places(private_film.plain), _drawn_places(private_film.run)

    assert any(word in caption for caption in plain for word in real), plain
    assert private, "the private film still captions its places"
    assert not [caption for caption in private if any(word in caption for word in real)], private


@pytest.mark.feature("privacy.privacy-mode")
def test_privacy_mode_scrambles_speech_into_a_low_murmur(private_film: PrivateFilm):
    voice_band = "highpass=f=800,highpass=f=800,"
    murmur_band = "lowpass=f=300,"
    film = private_film.run.film

    # In every source clip the voice band is as loud as the murmur band.
    for source in private_film.sources:
        assert abs(_level_db(source, voice_band) - _level_db(source, murmur_band)) < 6, source
    voice, murmur = _level_db(film, voice_band), _level_db(film, murmur_band)

    assert film_facts(film).has_audio
    assert murmur > -45, "people can still be heard talking"
    assert voice < murmur - 20, (voice, murmur)


@pytest.mark.feature("immich.never-modifies-originals")
def test_a_film_with_upload_off_only_reads_from_immich(private_film: PrivateFilm):
    sent = private_film.requests
    writes = [
        (method, path)
        for method, path in sent
        if method != "GET" and not (method == "POST" and path in _READ_ONLY_POSTS)
    ]

    assert any(path.endswith("/original") for _, path in sent), "the film read its originals"
    assert writes == []


# ── Immich v2 and v3 ─────────────────────────────────────────────────────────


@pytest.mark.feature("immich.v2-and-v3")
def test_a_v2_and_a_v3_server_both_make_a_film_and_config_test_names_the_version(
    library_home: UserHome, fake_immich: FakeImmichServer, tmp_path
):
    with fake_immich.answering_as(2):
        on_v2 = library_home.run("config", "test")
        film = render(
            library_home,
            *day_args(QUIET_DAY),
            "--output",
            str(tmp_path / "on-v2.mp4"),
            into=tmp_path,
        )
    on_v3 = library_home.run("config", "test")

    assert on_v2.returncode == 0, on_v2.explain()
    assert "API: v2" in on_v2.output
    assert film_facts(film.film).duration > 1
    # The v2 contract held every request the run sent; the session also fails on any.
    assert fake_immich.refused == []
    assert on_v3.returncode == 0, on_v3.explain()
    assert "API: v3" in on_v3.output


# ── outside calls ────────────────────────────────────────────────────────────


@pytest.mark.feature("privacy.outside-calls-opt-in")
def test_map_tiles_leave_the_network_only_once_switched_on(
    library_home: UserHome, fake_immich: FakeImmichServer, tmp_path
):
    default_preflight = library_home.run("preflight", scripted_selection=True)
    trap = OutboundTrap()
    try:
        home = UserHome(tmp_path / "home", extra_env=tuple(trap.env().items()))
        config = basic_config(fake_immich.base_url, fake_immich.api_key, home)
        config["network"] = {"geocoding": True, "map_tiles": True}
        home.write_config(config)
        opted_in_preflight = home.run("preflight", scripted_selection=True)
        before_the_film = list(trap.requests)
        trip = home.run(
            "generate",
            "--memory-type",
            "trip",
            "--year",
            "2024",
            "--trip-index",
            "1",
            "--include-photos",
            "--no-music",
            "--quiet",
            scripted_selection=True,
        )
    finally:
        trap.close()

    assert "Outside call" not in default_preflight.output
    assert re.search(
        r"Outside call: geocoding.*nominatim\.openstreetmap\.org", opted_in_preflight.output
    )
    assert re.search(
        r"Outside call: map_tiles.*server\.arcgisonline\.com", opted_in_preflight.output
    )
    # Naming a destination is not contacting it.
    assert before_the_film == []
    assert trip.returncode == 0, trip.explain()
    reached = {request.split()[1] for request in trap.requests}
    assert "server.arcgisonline.com:443" in reached
    assert reached <= {"server.arcgisonline.com:443", "nominatim.openstreetmap.org:443"}
