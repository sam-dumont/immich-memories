"""A remote film's music starts while the worker renders it, and is kept only if it fits (#2723).

The generator is the one boundary replaced: it counts how often a take is made and what each
take was asked for, so these tests prove which take the film got, never how long it took.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import pytest

from immich_memories.audio.music_generator_models import (
    GeneratedMusic,
    MusicGenerationResult,
    MusicStems,
)
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_music import resolve_music
from immich_memories.generate_music_early import EarlyMusic
from immich_memories.logging_config import RunIdFilter
from immich_memories.processing.assembly_config import AssemblyClip

FPS = 30.0


class _Generator:
    """The music backend: writes one take per call and remembers what each was asked for."""

    def __init__(self, *, fails: bool = False, hangs: bool = False, fails_once: bool = False):
        self.asked: list[tuple[float | None, tuple]] = []
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.fails = fails
        self.hangs = hangs
        self.fails_once = fails_once
        self.with_stems: list[bool] = []
        self.separated: list[Path] = []
        self.logged_as: list[logging.LogRecord] = []

    async def __call__(self, *, timeline, output_dir, progress_callback, **kwargs):
        number = len(self.asked)
        self.asked.append((timeline.film_duration, tuple(map(str, timeline.build_scenes()))))
        self.with_stems.append(kwargs.get("separate_stems", True))
        record = logging.LogRecord("music", logging.INFO, "", 0, "", None, None)
        RunIdFilter().filter(record)  # what a log line from the generator would carry
        self.logged_as.append(record)
        self.started.set()
        progress_callback(0, "generating", 50.0, None)
        if self.hangs:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        if self.fails or (self.fails_once and number == 0):
            raise RuntimeError("the music backend is down")
        track = output_dir / f"take_{number}.wav"
        track.write_bytes(b"RIFF")
        return MusicGenerationResult(
            versions=[GeneratedMusic(full_mix=track)], timeline=timeline, mood="calm"
        )


@pytest.fixture
def generator(request, monkeypatch) -> _Generator:
    made = _Generator(**getattr(request, "param", {}))
    # WHY: the generator is the model boundary (ACE-Step or MusicGen); everything else is real.
    monkeypatch.setattr("immich_memories.audio.music_generator.generate_music_for_video", made)

    async def separate(_config, track, _output_dir, _progress=None):
        made.separated.append(track)
        return MusicStems(vocals=track, accompaniment=track)

    # WHY: the stem separator (Demucs, maybe on the render worker's GPU) is a model boundary too.
    monkeypatch.setattr("immich_memories.audio.music_pipeline.separate_track", separate)
    return made


def _config() -> Config:
    config = Config()
    config.ace_step.enabled = True
    config.title_screens.enabled = False
    return config


def _film() -> list[AssemblyClip]:
    return [
        AssemblyClip(
            path=Path(f"clip-{number}.mp4"),
            asset_id=f"asset-{number}",
            duration=4.0,
            is_photo=number % 2 == 0,
            date="2024-06-04",
        )
        for number in range(8)
    ]


def _early(config: Config, run_dir: Path) -> EarlyMusic:
    return EarlyMusic(config, run_dir, memory_type=None, transition_overlap=0.5, attempt=None)


def _music_for(config, run_dir, early, *, seconds, report=None):
    """The music phase, as `run_music_phase` asks for it once the film has arrived."""
    return resolve_music(
        config=config,
        music_path=None,
        no_music=False,
        assembly_clips=_film(),
        run_output_dir=run_dir,
        memory_type=None,
        report_fn=report,
        transition_overlap=0.5,
        video_duration=seconds,
        fps=FPS,
        early=early,
    )


def test_the_film_that_arrives_as_expected_gets_the_early_take(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path)

    # The take is made for the longest film the worker may return; this one came back
    # shorter than the preview, as real renders do (by about a third of a second on 47 clips).
    early.begin(_film(), 30.5, FPS)
    selection = _music_for(config, tmp_path, early, seconds=29.7)

    assert len(generator.asked) == 1
    assert generator.asked[0][0] == 30.5
    assert selection.path == tmp_path / "music" / "take_0.wav"
    assert selection.path.exists()


def test_the_early_take_leaves_its_stems_until_the_film_is_back(tmp_path, generator):
    """The stem separator may be the render worker's GPU: it waits for the film."""
    config = _config()
    early = _early(config, tmp_path)

    early.begin(_film(), 30.0, FPS)
    assert generator.started.wait(10)
    assert generator.separated == []
    selection = _music_for(config, tmp_path, early, seconds=30.0)

    assert generator.with_stems == [False]
    assert generator.separated == [selection.path]
    assert selection.stems is not None


def test_the_early_take_logs_under_its_run(tmp_path, generator):
    from immich_memories.logging_config import set_current_run_id

    early = _early(_config(), tmp_path)
    set_current_run_id("run-with-music")
    try:
        early.begin(_film(), 30.0, FPS)
        assert generator.started.wait(10)
        early.cancel()
    finally:
        set_current_run_id(None)

    assert generator.logged_as[0].run_id == "run-with-music"


def test_a_take_made_after_the_film_keeps_its_own_stems(tmp_path, generator):
    _music_for(_config(), tmp_path, None, seconds=30.0)

    assert generator.with_stems == [True]
    assert generator.separated == []


def test_a_film_that_came_back_different_gets_music_made_for_it(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path)

    early.begin(_film(), 30.0, FPS)
    assert generator.started.wait(10)
    # Longer than the take: its music would end before the film.
    selection = _music_for(config, tmp_path, early, seconds=34.0)

    assert [asked[0] for asked in generator.asked] == [30.0, 34.0]
    assert generator.asked[0][1] != generator.asked[1][1]
    assert selection.path == tmp_path / "music" / "take_1.wav"
    assert not (tmp_path / "music" / "take_0.wav").exists()


def test_the_same_film_gets_the_same_music_with_or_without_a_head_start(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path / "early")
    early.begin(_film(), 30.0, FPS)

    _music_for(config, tmp_path / "early", early, seconds=30.0)
    _music_for(config, tmp_path / "plain", None, seconds=30.0)

    assert generator.asked[0] == generator.asked[1]


@pytest.mark.parametrize("generator", [{"fails": True}], indirect=True)
def test_a_failed_early_take_is_made_again_then_falls_back_as_always(tmp_path, generator):
    """An early take may fail only for sharing one small card with the render."""
    config = _config()
    early = _early(config, tmp_path)

    early.begin(_film(), 30.0, FPS)
    selection = _music_for(config, tmp_path, early, seconds=30.0)
    assert len(generator.asked) == 2  # the early take, then once more with the film back
    plain = _music_for(config, tmp_path / "plain", None, seconds=30.0)

    assert generator.asked[0] == generator.asked[1] == generator.asked[2]
    assert selection.warning == plain.warning
    assert selection.warning.startswith("Optional music failed: the music backend is down")


@pytest.mark.parametrize("generator", [{"fails_once": True}], indirect=True)
def test_an_early_take_that_ran_out_of_room_beside_the_render_is_made_after_it(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path)

    early.begin(_film(), 30.0, FPS)
    selection = _music_for(config, tmp_path, early, seconds=30.0)

    assert len(generator.asked) == 2
    assert selection.warning is None
    assert selection.path == tmp_path / "music" / "take_1.wav"


@pytest.mark.parametrize("generator", [{"hangs": True}], indirect=True)
def test_a_render_that_fails_stops_its_music_and_waits_for_it(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path)
    early.begin(_film(), 30.0, FPS)
    assert generator.started.wait(10)

    early.cancel()

    assert generator.cancelled.is_set()
    assert not [thread for thread in threading.enumerate() if thread.name == "early-music"]


def test_progress_from_the_early_take_waits_for_the_music_phase(tmp_path, generator):
    config = _config()
    early = _early(config, tmp_path)
    heard: list[tuple[str, float, str]] = []

    early.begin(_film(), 30.0, FPS)
    assert generator.started.wait(10)
    early.cancel()  # the take is over; nothing it said reached the render's progress

    assert heard == []
    _music_for(config, tmp_path, early, seconds=30.0, report=lambda *event: heard.append(event))
    assert heard and all(phase == "music" for phase, _, _ in heard)


def test_a_cancelled_head_start_never_hands_over_its_take(tmp_path, generator):
    """A render that fell back to the local machine stops the early take; the music phase
    makes its own once the film is drawn."""
    config = _config()
    early = _early(config, tmp_path)
    early.begin(_film(), 30.0, FPS)
    assert generator.started.wait(10)
    early.cancel()

    selection = _music_for(config, tmp_path, early, seconds=30.0)

    assert len(generator.asked) == 2
    assert selection.path == tmp_path / "music" / "take_1.wav"


WORKER = "https://render.example.lan:8092"


def _remote_params(tmp_path: Path, *, music_url: str = "http://music.example.lan:8000"):
    config = _config()
    config.ace_step.api_url = music_url
    config.render.worker_base_url = WORKER
    config.render.worker_token = "early-music-test-worker-token"  # noqa: S105
    return GenerationParams(clips=[], output_path=tmp_path / "film.mp4", config=config)


def test_a_local_render_keeps_the_device_to_itself(tmp_path):
    params = GenerationParams(clips=[], output_path=tmp_path / "film.mp4", config=_config())

    assert EarlyMusic.for_run(params, tmp_path) is None


def test_music_served_from_another_host_than_the_worker_gets_a_head_start(tmp_path):
    params = _remote_params(tmp_path)

    assert EarlyMusic.for_run(params, tmp_path) is not None
    params.no_music = True
    assert EarlyMusic.for_run(params, tmp_path) is None


@pytest.mark.parametrize(
    ("worker", "music"),
    [
        ("https://render.example.lan:8092", "http://RENDER.example.lan:8000"),
        ("http://127.0.0.1:8092", "http://localhost:8000"),
        ("http://[::1]:8092", "http://127.0.0.1:8001"),
    ],
)
def test_music_served_from_the_workers_host_waits_for_the_film(tmp_path, worker, music):
    """One machine serving both may share one card: the take would compete with the render."""
    params = _remote_params(tmp_path, music_url=music)
    params.config.render.worker_base_url = worker

    assert EarlyMusic.for_run(params, tmp_path) is None


def test_music_made_in_this_process_waits_for_the_film(tmp_path):
    """In-process ACE-Step uses this machine's device, which may be the worker's."""
    params = _remote_params(tmp_path)
    params.config.ace_step.mode = "lib"

    assert EarlyMusic.for_run(params, tmp_path) is None


def test_every_generator_has_to_be_apart_from_the_worker(tmp_path):
    params = _remote_params(tmp_path)
    params.config.musicgen.enabled = True
    params.config.musicgen.base_url = "http://render.example.lan:9000"

    assert EarlyMusic.for_run(params, tmp_path) is None
    params.config.musicgen.base_url = "http://musicgen.example.lan:9000"
    assert EarlyMusic.for_run(params, tmp_path) is not None


def test_a_server_that_will_not_run_xl_gets_no_head_start(tmp_path, monkeypatch):
    """The early take goes through the same XL gate as the music phase: no XL, no take."""
    from immich_memories.audio.generators import ace_step_music_path

    # WHY: the server's /health is the network boundary the gate reads.
    monkeypatch.setattr(ace_step_music_path, "server_model", lambda _url: "acestep-v15-turbo")

    assert EarlyMusic.for_run(_remote_params(tmp_path), tmp_path) is None
