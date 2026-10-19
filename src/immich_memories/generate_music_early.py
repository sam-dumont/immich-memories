"""Generated music started while a render worker draws the film (#2723).

A remote film's timeline is fixed when the app hands it to the worker, but its music used to
start only once the film came back: a take can take as long as the render. The app now
starts the take as soon as the worker has the job, from the film it expects back at its
longest (``expected_film``), and keeps the take only when the film that arrives asks for the
same music (``MusicPlan.mismatch``): the same scenes, cadence and mood, no longer than the
take. Anything else, and the early take is dropped and the music is made again from the film
itself, as it always was. The take's stems are separated once the film is back: the
separator is often the worker's own GPU.

The head start runs only where the take and the render cannot compete for one device: every
enabled generator is a server on another host than the worker (``music_apart_from_render``).
A local render, ACE-Step in this process, or a music server on the worker's own host keeps
the old order, film first: on one small shared card either side could run out of memory, and
the render could fall back to CPU titles or software encoding.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from immich_memories.audio.music_generator_models import GeneratedMusic
    from immich_memories.audio.text_mood import MusicMood
    from immich_memories.config.loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_music import MusicPlan
    from immich_memories.processing.assembly_config import AssemblyClip

logger = logging.getLogger(__name__)

Report = Callable[[str, float, str], None]
_T = TypeVar("_T")
# How often a waiting thread looks up, so a Ctrl-C or a cancelled run is never stuck behind it.
_POLL_SECONDS = 0.2


class MusicMemo(Protocol):
    """Where the music phase gets its mood and its take, when something already has them."""

    def mood(self, key: object, read_mood: Callable[[], MusicMood]) -> MusicMood: ...

    def take(
        self,
        plan: MusicPlan,
        make: Callable[[], GeneratedMusic | None],
        report: Report | None = None,
        finish: Callable[[GeneratedMusic], GeneratedMusic] | None = None,
    ) -> GeneratedMusic | None: ...


def early_music_wanted(params: GenerationParams) -> bool:
    """Whether this run renders on a worker and will generate its music apart from it.

    The music phase's own XL gate decides first (`ace_step_bundled_reason`): a film that
    will play a bundled track has no take to start.
    """
    from immich_memories.generate_music import ace_step_bundled_reason, music_config_available

    config = params.config
    return bool(
        config.render.enabled
        and not params.no_music
        and params.music_path is None
        and music_config_available(config)
        and music_apart_from_render(config)
        and ace_step_bundled_reason(config) is None
    )


def music_apart_from_render(config: Config) -> bool:
    """Whether every enabled generator is a server on another host than the render worker.

    Only then can the two not compete for one card. ACE-Step in this process uses this
    machine's device, and a server on the worker's own host may share the worker's GPU:
    both keep the old order, film first. Two services on one card under different names
    (time-sliced pods, containers) cannot be told apart from here.
    """
    worker = _host(config.render.worker_base_url)
    servers: list[str] = []
    if config.ace_step.enabled:
        if config.ace_step.mode != "api":
            return False
        servers.append(config.ace_step.api_url)
    if config.musicgen.enabled:
        servers.append(config.musicgen.base_url)
    hosts = [_host(url) for url in servers]
    return bool(hosts) and all(host and host != worker for host in hosts)


def _host(url: str) -> str:
    """The machine a URL points at: its host name, with every loopback name as one."""
    from urllib.parse import urlsplit

    from immich_memories.config.models.render import is_loopback_host

    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return "loopback" if host and is_loopback_host(host) else host


class EarlyMusic:
    """One film's music take, started before its film exists; used only if the film matches.

    ``begin`` starts the take in a thread from the film the worker is expected to return.
    The music phase then asks ``mood`` and ``take`` with what the returned film needs; each
    answers from the early take when it was made from the same inputs and otherwise runs the
    work it was handed. ``cancel`` stops a take that is no longer wanted and waits for it, so
    no generation outlives the run.
    """

    def __init__(
        self,
        config: Config,
        run_output_dir: Path,
        *,
        memory_type: str | None,
        transition_overlap: float,
        attempt: Path | None,
    ) -> None:
        self._config = config
        self._run_output_dir = run_output_dir
        self._memory_type = memory_type
        self._transition_overlap = transition_overlap
        self._attempt = attempt
        self._thread: threading.Thread | None = None
        self._cancelled = threading.Event()
        self._finished = threading.Event()
        self._lock = threading.Lock()
        self._report: Report | None = None
        self._mood: tuple[object, MusicMood] | None = None
        self._mood_ready = threading.Event()
        self._plan: MusicPlan | None = None
        self._plan_ready = threading.Event()
        self._made = threading.Event()
        self._outcome: GeneratedMusic | None = None
        self._failure: BaseException | None = None

    @classmethod
    def for_run(
        cls, params: GenerationParams, run_output_dir: Path, *, deferred: bool = False
    ) -> EarlyMusic | None:
        """The head start this run may use, or None when it renders locally or makes no music.

        A ``deferred`` run hands its film back before music, so it never mixes one here.
        """
        if deferred or not early_music_wanted(params):
            return None
        from immich_memories.generate_music import transition_overlap_seconds

        return cls(
            params.config,
            run_output_dir,
            memory_type=params.memory_type,
            transition_overlap=transition_overlap_seconds(
                params.transition, params.transition_duration
            ),
            attempt=params.editorial_attempt_dir,
        )

    def begin(
        self, clips: Sequence[AssemblyClip], video_duration: float | None, fps: float
    ) -> None:
        """Start the take from the film the worker is expected to return."""
        if self._thread is not None or self._cancelled.is_set():
            return
        logger.info("Generating the film's music while the worker renders it")
        # The run's context (its id on every log line) follows the take into its thread.
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run,
            args=(self._work, list(clips), video_duration, fps),
            name="early-music",
        )
        self._thread.start()

    def _work(self, clips: list[AssemblyClip], video_duration: float | None, fps: float) -> None:
        from immich_memories.generate_music import auto_generate_music, music_evidence

        recorder = _Recorder(self)
        try:
            clips, _mood, mood_detail = music_evidence(
                self._config, clips, self._attempt, self._memory_type, early=recorder
            )
            auto_generate_music(
                self._config,
                clips,
                self._run_output_dir,
                self._memory_type,
                self._relay,
                transition_overlap=self._transition_overlap,
                fps=fps,
                mood_detail=mood_detail,
                video_duration=video_duration,
                early=recorder,
                run=self._run,
                # The separator may be the render worker's own GPU: stems wait for the film.
                separate_stems=False,
            )
        except BaseException as error:  # WHY: the film's own music phase decides what fails
            logger.debug("The early music take stopped: %s", type(error).__name__)
        finally:
            self._finished.set()

    def _run(self, work: Coroutine[Any, Any, _T]) -> _T:
        """Drive the generation where ``cancel`` can stop it at its next await."""

        async def until_done_or_cancelled() -> _T:
            task = asyncio.ensure_future(work)
            while not task.done():
                if self._cancelled.is_set():
                    task.cancel()
                await asyncio.wait({task}, timeout=_POLL_SECONDS)
            return task.result()

        return asyncio.run(until_done_or_cancelled())

    def _relay(self, phase: str, progress: float, message: str) -> None:
        # Until the music phase starts, the run's progress belongs to the render.
        with self._lock:
            report = self._report
        if report is not None:
            report(phase, progress, message)

    def _wait_for(self, event: threading.Event) -> bool:
        """Wait for ``event`` unless the take ended first; False when there never was one."""
        if self._thread is None:
            return False
        while not (event.is_set() or self._finished.is_set()):
            event.wait(_POLL_SECONDS)
        return event.is_set()

    def mood(self, key: object, read_mood: Callable[[], MusicMood]) -> MusicMood:
        """The early take's mood when it was read from the same film, else ``read_mood()``."""
        if self._wait_for(self._mood_ready) and self._mood is not None and self._mood[0] == key:
            return self._mood[1]
        return read_mood()

    def take(
        self,
        plan: MusicPlan,
        make: Callable[[], GeneratedMusic | None],
        report: Report | None = None,
        finish: Callable[[GeneratedMusic], GeneratedMusic] | None = None,
    ) -> GeneratedMusic | None:
        """The early take when it was made from ``plan``, else a take ``make()`` makes now.

        ``finish`` completes a handed-over take (its stems, separated now the render is done).

        A take that failed is made again now: it may have failed only for sharing a device
        with the render (one small card serving both), and the film is back. A second failure
        reaches the music phase, which falls back exactly as it always did.
        """
        recorded = self._plan if self._wait_for(self._plan_ready) else None
        if self._cancelled.is_set():
            recorded = None
        mismatch = "never started" if recorded is None else recorded.mismatch(plan)
        if mismatch is not None:
            if recorded is not None:
                logger.info(
                    "The early music take does not fit the film (%s); making the music again",
                    mismatch,
                )
            self.discard()
            return make()
        with self._lock:
            self._report = report
        while not self._made.wait(_POLL_SECONDS):
            pass
        if isinstance(self._failure, Exception):
            logger.info("The early music take failed; making the music again now")
            self.discard()
            return make()
        if self._failure is not None:
            raise self._failure
        if self._outcome is not None and finish is not None:
            return finish(self._outcome)
        return self._outcome

    def cancel(self) -> None:
        """Stop a take that is no longer wanted and wait for it: nothing outlives the run."""
        self._cancelled.set()
        if self._thread is not None:
            self._thread.join()

    def discard(self) -> None:
        """Cancel the take and remove what it wrote, so a fresh take starts from nothing."""
        self.cancel()
        if self._outcome is not None:
            self._outcome.cleanup()
            self._outcome = None


class _Recorder:
    """What the early take's thread passes for ``early``: it does the work and notes it."""

    def __init__(self, early: EarlyMusic) -> None:
        self._early = early

    def mood(self, key: object, read_mood: Callable[[], MusicMood]) -> MusicMood:
        chosen = read_mood()
        self._early._mood = (key, chosen)
        self._early._mood_ready.set()
        return chosen

    def take(
        self,
        plan: MusicPlan,
        make: Callable[[], GeneratedMusic | None],
        report: Report | None = None,
        finish: Callable[[GeneratedMusic], GeneratedMusic] | None = None,
    ) -> GeneratedMusic | None:
        early = self._early
        early._plan = plan
        early._plan_ready.set()
        try:
            early._outcome = make()
        except BaseException as error:  # WHY: handed to the music phase, which owns the fallback
            early._failure = error
        finally:
            early._made.set()
        return early._outcome
