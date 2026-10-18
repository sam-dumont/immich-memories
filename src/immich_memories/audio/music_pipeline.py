"""Multi-provider music generation pipeline.

Orchestrates music generation and optional stem separation:
1. ACE-Step — generation in direct-library or API mode
2. MusicGen — generation behind ACE-Step in the fallback chain, and remote
   Demucs stems

Stem separation is decoupled from generation via the StemSeparator protocol:
- DemucsLocalBackend: in-process, no server needed (Apple Silicon / CUDA / CPU)
- MusicGenBackend: remote API with Demucs endpoint
- Auto-detected: if demucs package is installed, uses local; otherwise MusicGen API
"""

from __future__ import annotations

import logging
import math
import secrets
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from immich_memories.audio.generated_audio import validate_generated_audio
from immich_memories.audio.generators.base import (
    GenerationRequest,
    GenerationResult,
    MusicGenerator,
    StemSeparator,
)
from immich_memories.audio.mastering import master_music_track
from immich_memories.audio.music_generator_models import (
    GeneratedMusic,
    MusicGenerationResult,
    MusicStems,
    VideoTimeline,
)
from immich_memories.audio.take_join import join_takes, trim_take

if TYPE_CHECKING:
    from immich_memories.audio.mood_analyzer import VideoMood
    from immich_memories.audio.track_quality import TrackQuality

logger = logging.getLogger(__name__)

# A film longer than this is joined from takes on bar lines: one take per film of any
# length sounded bland and kept tripping the loop check (#2617), while 90 s takes hold
# together (the bundled music library is made of them).
_TAKE_SECONDS = 90


class MusicPipeline:
    """Music generation pipeline with ordered-backend fallback support.

    Tries every configured generator in order, so a backend that is enabled but
    failing costs the run its first choice rather than its music. Stem
    separation is decoupled via local Demucs or the MusicGen API.
    """

    def __init__(
        self,
        generators: list[MusicGenerator],
        stem_separator: StemSeparator | None = None,
        *,
        block_seconds: int = _TAKE_SECONDS,
        max_blocks: int = 3,
    ):
        self._generators = generators
        self._stem_separator = stem_separator
        self._block_seconds = block_seconds
        self._max_blocks = max_blocks

    async def __aenter__(self):
        for gen in self._generators:
            await gen.__aenter__()
        sep = self._stem_separator
        if sep and sep not in self._generators and hasattr(sep, "__aenter__"):
            await sep.__aenter__()
        return self

    async def __aexit__(self, *args):
        for gen in self._generators:
            await gen.__aexit__(*args)
        sep = self._stem_separator
        if sep and sep not in self._generators and hasattr(sep, "__aexit__"):
            await sep.__aexit__(*args)

    async def generate_music_for_video(
        self,
        timeline: VideoTimeline,
        output_dir: Path,
        num_versions: int = 3,
        progress_callback: Any | None = None,
        crossfade_duration: float = 2.0,
        hemisphere: str = "north",
        memory_type: str | None = None,
        photo_cadence_seconds: float | None = None,
        *,
        mood_detail: VideoMood | None = None,
        quality_gate: Callable[[Path], TrackQuality | None] | None = None,
    ) -> MusicGenerationResult:
        """Generate music using the first available backend, with fallback.

        ``mood_detail`` carries the reader's full music judgment (energy, tempo,
        genre yields) to backends that can use richer prompts than a bare mood
        word. ``quality_gate`` turns the version loop into a bounded regenerate:
        each take's full mix is scored once it is mastered, the loop stops early
        as soon as a take is not flagged, and stems are separated only for the
        best-scored take. Without it the loop generates every version and
        separates stems for each, which is what the UI preview needs.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        scenes = timeline.build_scenes(hemisphere=hemisphere)
        total_duration = timeline.music_duration
        primary_mood = scenes[0]["mood"] if scenes else "calm"

        logger.info(
            "Pipeline: %d scenes, %.1fs of music, %d versions",
            len(scenes),
            total_duration,
            num_versions,
        )

        if quality_gate is not None:
            return await self._generate_gated(
                timeline=timeline,
                scenes=scenes,
                total_duration=total_duration,
                primary_mood=primary_mood,
                output_dir=output_dir,
                num_versions=num_versions,
                progress_callback=progress_callback,
                crossfade_duration=crossfade_duration,
                memory_type=memory_type,
                photo_cadence_seconds=photo_cadence_seconds,
                mood_detail=mood_detail,
                quality_gate=quality_gate,
            )

        versions: list[GeneratedMusic] = []

        for i in range(num_versions):
            logger.info(f"Generating version {i + 1}/{num_versions}")

            made = await self._generate_full_mix(
                scenes=scenes,
                primary_mood=primary_mood,
                total_duration=total_duration,
                output_dir=output_dir,
                crossfade_duration=crossfade_duration,
                memory_type=memory_type,
                photo_cadence_seconds=photo_cadence_seconds,
                mood_detail=mood_detail,
                candidate_index=i,
                num_versions=num_versions,
                progress_callback=progress_callback,
            )
            if made is None:
                backend_names = ", ".join(g.name for g in self._generators)
                logger.error(
                    "All music backends failed for version %d/%d (tried: %s)",
                    i + 1,
                    num_versions,
                    backend_names,
                )
                continue

            result, request = made
            stems = await self._try_separate_stems(result, request, progress_callback, i)

            versions.append(
                GeneratedMusic(
                    full_mix=result.audio_path,
                    stems=stems,
                    duration=total_duration,
                    prompt=result.prompt,
                    mood=primary_mood,
                )
            )

        if not versions:
            raise RuntimeError("All music generation backends failed for all versions")

        return MusicGenerationResult(
            versions=versions,
            timeline=timeline,
            mood=primary_mood,
        )

    async def _generate_gated(
        self,
        timeline: VideoTimeline,
        scenes: list[dict[str, Any]],
        total_duration: float,
        primary_mood: str,
        output_dir: Path,
        num_versions: int,
        progress_callback: Any | None,
        crossfade_duration: float,
        memory_type: str | None,
        photo_cadence_seconds: float | None,
        mood_detail: VideoMood | None,
        quality_gate: Callable[[Path], TrackQuality | None],
    ) -> MusicGenerationResult:
        """Bounded regenerate: score each take, stop early, separate the winner."""

        candidates: list[tuple[GenerationRequest, GenerationResult, TrackQuality | None]] = []

        for i in range(num_versions):
            logger.info(f"Generating version {i + 1}/{num_versions}")

            made = await self._generate_full_mix(
                scenes=scenes,
                primary_mood=primary_mood,
                total_duration=total_duration,
                output_dir=output_dir,
                crossfade_duration=crossfade_duration,
                memory_type=memory_type,
                photo_cadence_seconds=photo_cadence_seconds,
                mood_detail=mood_detail,
                candidate_index=i,
                num_versions=num_versions,
                progress_callback=progress_callback,
            )
            if made is None:
                continue

            result, request = made
            quality = quality_gate(result.audio_path)
            candidates.append((request, result, quality))
            logger.info(
                "Version %d scored %s",
                i + 1,
                "no verdict"
                if quality is None
                else f"periodicity={quality.periodicity:.2f} "
                f"spikiness={quality.spikiness:.2f} flagged={quality.flagged}",
            )

            if quality is not None and not quality.flagged:
                break  # accepted; do not spend further regenerations

        if not candidates:
            raise RuntimeError("All music generation backends failed for all versions")

        request, result, quality = _best_candidate(candidates)
        stems = await self._try_separate_stems(result, request, progress_callback, 0)

        versions = [
            GeneratedMusic(
                full_mix=result.audio_path,
                stems=stems,
                duration=total_duration,
                prompt=result.prompt,
                mood=primary_mood,
            )
        ]

        return MusicGenerationResult(
            versions=versions,
            timeline=timeline,
            mood=primary_mood,
            selected_version=0,
        )

    async def _generate_full_mix(
        self,
        *,
        scenes: list[dict[str, Any]],
        primary_mood: str,
        total_duration: float,
        output_dir: Path,
        crossfade_duration: float,
        memory_type: str | None,
        photo_cadence_seconds: float | None,
        mood_detail: VideoMood | None,
        candidate_index: int,
        num_versions: int,
        progress_callback: Any | None,
    ) -> tuple[GenerationResult, GenerationRequest] | None:
        """One mastered full-length mix (and its request), pre-stem.

        The whole film comes from the first backend that can make it, never a
        block from one backend and the next block from another. Within the
        backend's take length it is one take. Longer, its takes share one seed,
        so they share the caption, style, BPM and key, and are joined on bar
        lines with a short crossfade (``join_takes``). Takes used to be separate
        songs crossfaded blind for two seconds, so two melodies played at every
        seam (#2472). The result is mastered once, so stems and ducking see a
        balanced track.
        """
        request = GenerationRequest(
            prompt=primary_mood,
            scenes=scenes,
            duration_seconds=math.ceil(total_duration),
            variation_index=candidate_index,
            crossfade_duration=crossfade_duration,
            output_dir=output_dir,
            memory_type=memory_type,
            photo_cadence_seconds=photo_cadence_seconds,
            mood_detail=mood_detail,
            seed=secrets.randbelow(_SEED_RANGE),
        )
        progress = _VersionProgress(progress_callback, candidate_index)
        for gen in self._generators:
            if not await _is_ready(gen, progress):
                continue
            take_seconds = self._take_seconds(gen)
            if take_seconds is None or total_duration + _JOIN_MARGIN_SECONDS <= take_seconds:
                made = await _run(gen, _past_the_end(request), progress)
                if made is not None:
                    made = _cut_to_film(made, total_duration, output_dir, candidate_index)
            else:
                made = await self._joined_takes(
                    gen, request, total_duration, take_seconds, progress
                )
            if made is not None:
                made.audio_path = master_music_track(
                    made.audio_path, output_dir / f"mastered_version_{candidate_index}.wav"
                )
                return made, request
        return None

    def _take_seconds(self, gen: MusicGenerator) -> int | None:
        """The longest take to ask this backend for, or None when it covers any film."""
        cap = gen.max_take_seconds
        return None if cap is None else min(self._block_seconds, cap)

    async def _joined_takes(
        self,
        gen: MusicGenerator,
        film: GenerationRequest,
        total_duration: float,
        take_seconds: int,
        progress: _VersionProgress,
    ) -> GenerationResult | None:
        """Several takes of one musical identity from one backend, joined on bar lines."""
        usable = max(take_seconds - _JOIN_MARGIN_SECONDS, 1)
        count = min(self._max_blocks, math.ceil(total_duration / usable))
        length = min(take_seconds, math.ceil(total_duration / count) + _JOIN_MARGIN_SECONDS)
        takes: list[GenerationResult] = []
        for index in range(count):
            take = replace(
                film,
                duration_seconds=length,
                duration_limit_seconds=length,
                variation_index=index,
            )
            result = await _run(gen, take, progress)
            if result is None:
                logger.warning("Music take %d/%d failed; skipping", index + 1, count)
                continue
            takes.append(result)
            logger.info("Music take %d/%d ready", len(takes), count)
        if not takes:
            return None

        bpm = takes[0].metadata.get("bpm")
        logger.info(
            "Joining %d takes of %ss into %.1fs on a %s bpm bar grid",
            len(takes),
            length,
            total_duration,
            bpm or "measured",
        )
        joined = join_takes(
            [take.audio_path for take in takes],
            total_duration,
            film.output_dir / f"chained_version_{film.variation_index}.wav",
            bpm=bpm if isinstance(bpm, int | float) else None,
        )
        return GenerationResult(
            audio_path=joined,
            duration_seconds=total_duration,
            prompt=takes[0].prompt,
            backend_name=takes[0].backend_name,
            metadata=takes[0].metadata.copy(),
        )

    async def _try_separate_stems(
        self,
        result: GenerationResult,
        request: GenerationRequest,
        progress_callback: Any | None,
        version_idx: int,
    ) -> MusicStems | None:
        """Separate stems using any StemSeparator (local Demucs or MusicGen API)."""
        if self._stem_separator is None:
            return None

        def _progress(status, progress, detail):
            if progress_callback:
                scaled = 80 + progress * 0.2
                progress_callback(version_idx, f"Separating stems: {status}", scaled, detail)

        try:
            _progress("Checking stem separator", 0, None)
            if not await self._stem_separator.is_available():
                logger.warning("Stem separator unavailable, skipping")
                return None

            # WHY a directory per version: Demucs writes fixed stem filenames
            # (vocals.wav, drums.wav...), so three versions separating into one
            # directory left one set of stems belonging to whichever finished
            # last, silently attributed to all three.
            stem_dir = request.output_dir / f"version_{version_idx}"
            stem_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Separating stems with {self._stem_separator.name}")
            return await self._stem_separator.separate_stems(
                result.audio_path,
                output_dir=stem_dir,
                progress_callback=_progress,
            )

        except Exception:
            # WHY broad: same reasoning as the backend chain — stems are a
            # bonus, and no way of failing to produce them should cost the
            # music that was already generated.
            # No exc_info, for the same reason as the backend chain above.
            logger.warning("Stem separation failed; continuing without stems")
            return None


# A take is asked this much longer than its share of the film: it ends on an outro and
# then silence. The join drops those closing bars and starts the next take on a downbeat;
# a film's last take runs past the last frame, where the mix cuts and fades it.
_JOIN_MARGIN_SECONDS = 8


def _cut_to_film(
    made: GenerationResult, total_duration: float, output_dir: Path, candidate_index: int
) -> GenerationResult:
    """The take cut at the film's length, its outro left past the last frame."""
    cut = trim_take(made.audio_path, total_duration, output_dir / f"take_cut_{candidate_index}.wav")
    return replace(made, audio_path=cut, duration_seconds=total_duration)


def _past_the_end(film: GenerationRequest) -> GenerationRequest:
    """A one-take film's request, asked to run past the film's end.

    Asked for the film's own length, the take went quiet three to four seconds before the
    last frame and the ending card played over silence.
    """
    length = film.duration_seconds + _JOIN_MARGIN_SECONDS
    return replace(film, duration_seconds=length, duration_limit_seconds=length)


# A film's seed leaves room for its takes to step from it without wrapping.
_SEED_RANGE = 2**30


class _VersionProgress:
    """Progress for one candidate version, scaled to the generation share."""

    def __init__(self, callback: Any | None, version_idx: int):
        self._callback = callback
        self._version_idx = version_idx

    def __call__(self, status: str, progress: float, detail: Any) -> None:
        if self._callback:
            self._callback(self._version_idx, status, progress * 0.8, detail)


async def _is_ready(gen: MusicGenerator, progress: _VersionProgress) -> bool:
    try:
        progress("Checking music service", 0, None)
        if await gen.is_available():
            return True
        logger.info(f"{gen.name} unavailable, trying next...")
    except Exception:
        # WHY broad: see _run; a backend's availability probe fails in its own vocabulary.
        logger.warning("Music backend %s failed; trying next backend", gen.name)
    return False


async def _run(
    gen: MusicGenerator, request: GenerationRequest, progress: _VersionProgress
) -> GenerationResult | None:
    """One request on one backend, or None when it fails or makes unusable audio."""
    try:
        logger.info(f"Generating with {gen.name}")
        progress("Generating music", 0, None)
        result = await gen.generate(request, progress)
    except Exception:
        # WHY broad: the point of a backend chain is that one backend
        # failing is not the run failing, and each backend fails in its
        # own vocabulary — a hosted one raises httpx.HTTPStatusError,
        # which is neither RuntimeError nor OSError and used to escape
        # the chain entirely. CancelledError is a BaseException and
        # still propagates.
        # No exc_info: a backend's exception text can carry its URL or
        # key, and these logs are kept deliberately quiet about that.
        progress("Music service failed; trying the next service", 0, None)
        logger.warning("Music backend %s failed; trying next backend", gen.name)
        return None
    if reason := validate_generated_audio(result.audio_path):
        logger.warning("Music backend %s rejected: %s; trying next backend", gen.name, reason)
        return None
    return result


def _candidate_rank(
    candidate: tuple[GenerationRequest, GenerationResult, TrackQuality | None],
) -> float:
    """Degeneracy for ranking, with an unscorable take ranked worst."""
    quality = candidate[2]
    return quality.score if quality is not None else 1.0


def _best_candidate(
    candidates: list[tuple[GenerationRequest, GenerationResult, TrackQuality | None]],
) -> tuple[GenerationRequest, GenerationResult, TrackQuality | None]:
    """The least tick-like take, falling back to the first when none can be scored."""
    scored = [c for c in candidates if c[2] is not None]
    pool = scored if scored else candidates
    return min(pool, key=_candidate_rank)


def create_pipeline(app_config, *, separate_stems: bool = True) -> MusicPipeline:
    """Create a MusicPipeline from the application config.

    Reads musicgen and ace_step sections from the app config to build
    the generator priority list and stem separator.

    Stem separation priority:
    1. MusicGen API (if enabled) — established, supports 2-stem and 4-stem
    2. Owned inference service (if configured), with optional local fallback
    3. Local Demucs (if demucs package installed) — zero-config fallback

    ``separate_stems=False`` skips the separator for callers that only need a
    full track. CLI and UI generation retain stems for the final mix.
    """
    from immich_memories.audio.generators.factory import create_generator

    generators: list[MusicGenerator] = []
    stem_separator: StemSeparator | None = None

    # ACE-Step as primary generator (if enabled)
    ace_step_enabled = getattr(app_config, "ace_step", None) and app_config.ace_step.enabled
    if ace_step_enabled:
        generators.append(create_generator("ace_step", app_config.ace_step))
        logger.info(f"Pipeline: ACE-Step enabled (mode={app_config.ace_step.mode})")

    # MusicGen: stem separator always, and generation behind ACE-Step in the chain.
    # It used to be added as a generator only when ACE-Step was off, which left
    # `generators` one element long in every configuration and made the fallback
    # chain unreachable (#499).
    if getattr(app_config, "musicgen", None) and app_config.musicgen.enabled:
        musicgen = create_generator("musicgen", app_config.musicgen)
        if separate_stems:
            # MusicGenBackend satisfies StemSeparator (has separate_stems method)
            stem_separator = musicgen  # type: ignore[assignment]
        generators.append(musicgen)
        role = "fallback generation" if ace_step_enabled else "generation"
        logger.info(
            "Pipeline: MusicGen enabled (%s%s)",
            role,
            " + Demucs stems" if separate_stems else "",
        )

    inference_url = getattr(getattr(app_config, "inference", None), "facts_base_url", "")
    if (
        separate_stems
        and stem_separator is None
        and isinstance(inference_url, str)
        and inference_url
    ):
        from immich_memories.audio.generators.inference_demucs import InferenceDemucs

        fallback = _try_local_demucs() if app_config.inference.fallback_to_local else None
        stem_separator = InferenceDemucs(inference_url, fallback=fallback)

    # Auto-detect local Demucs when no remote separator is configured.
    if separate_stems and stem_separator is None:
        stem_separator = _try_local_demucs()

    if not generators:
        raise ValueError(
            "No music generation backends enabled. "
            "Enable at least one of: musicgen.enabled, ace_step.enabled"
        )

    return MusicPipeline(
        generators=generators,
        stem_separator=stem_separator,
        block_seconds=_block_seconds(app_config),
        max_blocks=_max_blocks(app_config),
    )


def _block_seconds(app_config) -> int:
    """The longest single take before auto mode joins takes of one identity."""
    audio = getattr(app_config, "audio", None)
    value = getattr(audio, "music_block_seconds", None)
    return value if isinstance(value, int) and value > 0 else _TAKE_SECONDS


def _max_blocks(app_config) -> int:
    """Distinct takes to chain for a video longer than the block length."""
    audio = getattr(app_config, "audio", None)
    value = getattr(audio, "max_music_blocks", None)
    return value if isinstance(value, int) and value > 0 else 3


def _try_local_demucs() -> StemSeparator | None:
    """Create a local Demucs backend if the package is installed."""
    from contextlib import suppress

    with suppress(ImportError):
        from immich_memories.audio.generators.demucs_local import (
            DemucsLocalBackend,
            is_demucs_importable,
        )

        if is_demucs_importable():
            logger.info("Pipeline: Local Demucs detected — using for stem separation")
            return DemucsLocalBackend()

    logger.info("Pipeline: No stem separator available (install demucs or enable musicgen)")
    return None
