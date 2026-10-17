"""Real-FFmpeg check that a long film plays one library track, looped on its own bar lines.

A film longer than its bundled track, or a track from your music folder, plays that one
track for its whole length: no second track joins it. The loop meets itself on a bar
line in a short crossfade, so the bar grid runs straight on, the level never dips at a
seam, no splice clicks, and the music still fades out at the film's last second.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from immich_memories.config.loader import Config
from immich_memories.generate_music import resolve_music
from tests.integration.audio_mixing.test_take_join import (
    BAR,
    BEAT,
    RATE,
    TONE_A,
    TONE_B,
    _accent_times,
    _mono,
    _tone_levels,
    _write_take,
)

# WHY: FFmpeg only, no ML model, so it is not pinned to the heavy audio_ml xdist group.
pytestmark = pytest.mark.integration

TRACK_SECONDS = 12.0
FILM_SECONDS = 3 * TRACK_SECONDS
FADE_SECONDS = 2.0


def _library(root: Path) -> Path:
    """Two calm tracks at the same tempo over different tones, laid out like the bundle."""
    folder = root / "calm"
    folder.mkdir(parents=True)
    _write_take(folder / "a.wav", hz=TONE_A, phase=0.13, level=0.4, seconds=TRACK_SECONDS)
    _write_take(folder / "b.wav", hz=TONE_B, phase=0.31, level=0.4, seconds=TRACK_SECONDS)
    return root


def _empty(folder: Path) -> Path:
    folder.mkdir(parents=True)
    return folder


def _config(own_folder: Path | None) -> Config:
    config = Config()
    config.ace_step.enabled = config.musicgen.enabled = False
    if own_folder is not None:
        config.audio.local_music_dir = str(own_folder)
    return config


@pytest.fixture(params=["bundled", "own folder"])
def film_music(request: pytest.FixtureRequest, tmp_path: Path) -> np.ndarray:
    library = _library(tmp_path / "library")
    own = request.param == "own folder"
    selection = resolve_music(
        _config(library if own else None),
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path / "run",
        memory_type=None,
        # An empty bundle, so the own-folder film can only play your track.
        bundled_library=_empty(tmp_path / "bundle") if own else library,
        transition_overlap=0.0,
        video_duration=FILM_SECONDS,
    )
    assert selection.path is not None
    return _mono(selection.path)


def _body(samples: np.ndarray) -> np.ndarray:
    """The film's music before its closing fade."""
    return samples[: int((FILM_SECONDS - FADE_SECONDS - 0.5) * RATE)]


def test_the_music_lasts_the_whole_film(film_music: np.ndarray) -> None:
    assert film_music.size / RATE == pytest.approx(FILM_SECONDS, abs=0.1)


def test_one_track_plays_the_whole_film(film_music: np.ndarray) -> None:
    body = _body(film_music)
    a, b = _tone_levels(body, TONE_A), _tone_levels(body, TONE_B)
    chosen, other = (a, b) if a.mean() > b.mean() else (b, a)

    assert other.max() < 0.05 * chosen.max(), "a second track joined the loop"


def test_the_bar_grid_runs_on_across_every_loop(film_music: np.ndarray) -> None:
    gaps = np.diff(_accent_times(_body(film_music)))

    assert gaps.size >= int(FILM_SECONDS / BAR) - 3
    assert np.all(np.abs(gaps - BAR) < 0.06), gaps


def test_the_loop_seams_neither_dip_nor_click(film_music: np.ndarray) -> None:
    body = _body(film_music)[int(0.2 * RATE) :]
    a, b = _tone_levels(body, TONE_A), _tone_levels(body, TONE_B)
    tone = a if a.mean() > b.mean() else b
    median = np.median(tone)

    # A gap or an out-of-phase splice shows as the sustained tone dropping away.
    assert tone.min() > 0.5 * median
    # A splice click is one sample step far larger than the sustained tone ever takes;
    # the bar accents are broadband by design, so they are left out.
    steps = np.abs(np.diff(body))
    between_beats = np.ones(steps.size, dtype=bool)
    for downbeat in _accent_times(body):
        for at in downbeat + BEAT * np.arange(-4, 4):
            between_beats[max(int((at - 0.01) * RATE), 0) : int((at + 0.02) * RATE)] = False
    tone_steps = steps[between_beats]
    assert tone_steps.max() < 1.5 * np.percentile(tone_steps, 99.9)


def test_the_music_fades_out_on_the_films_last_second(film_music: np.ndarray) -> None:
    def rms(start: float, end: float) -> float:
        part = film_music[int(start * RATE) : int(end * RATE)]
        return float(np.sqrt(np.mean(np.square(part))))

    body = rms(FILM_SECONDS - 6.0, FILM_SECONDS - 2.5)

    assert rms(FILM_SECONDS - 0.1, FILM_SECONDS) < 0.1 * body
    assert rms(FILM_SECONDS - 1.0, FILM_SECONDS - 0.5) < 0.6 * body
