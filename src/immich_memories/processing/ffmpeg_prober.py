"""FFmpeg-based video probing service."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TransitionType,
)
from immich_memories.processing.probe_cache import ProbeCache, ProbeError

logger = logging.getLogger(__name__)


class FFmpegProber:
    """FFmpeg-based implementation of video probing.

    Source metadata comes from one caller-owned cache. ``estimate_duration``
    additionally uses ``self.settings`` for transition config.
    """

    def __init__(
        self,
        settings: AssemblySettings,
        *,
        probe_cache: ProbeCache | None = None,
    ) -> None:
        self.settings = settings
        self.probe_cache = probe_cache or ProbeCache()

    def get_video_resolution(self, video_path: Path) -> tuple[int, int] | None:
        """Get resolution accounting for rotation (iPhones store portrait as rotated landscape)."""
        try:
            return self.probe_cache.get(video_path).resolution
        except (OSError, ProbeError, ValueError) as e:
            logger.debug(f"Failed to detect resolution: {e}")
        return None

    def pick_resolution_tier(
        self,
        resolution_counts: dict[str, int],
        total: int,
        orientation_str: str,
        res_4k: tuple[int, int],
        res_1080p: tuple[int, int],
        res_720p: tuple[int, int],
    ) -> tuple[int, int]:
        if resolution_counts["4k"] > total / 2:
            logger.info(
                f"Auto resolution: 4K {orientation_str} ({resolution_counts['4k']}/{total} clips are 4K)"
            )
            return res_4k
        if resolution_counts["1080p"] > total / 2:
            logger.info(
                f"Auto resolution: 1080p {orientation_str} ({resolution_counts['1080p']}/{total} clips are 1080p)"
            )
            return res_1080p
        if resolution_counts["720p"] > total / 2:
            logger.info(
                f"Auto resolution: 720p {orientation_str} ({resolution_counts['720p']}/{total} clips are 720p)"
            )
            return res_720p
        # No majority — use highest present
        if resolution_counts["4k"] > 0:
            logger.info(
                f"Auto resolution: 4K {orientation_str} (highest available, {resolution_counts['4k']}/{total} clips)"
            )
            return res_4k
        if resolution_counts["1080p"] > 0:
            logger.info(
                f"Auto resolution: 1080p {orientation_str} (highest available, {resolution_counts['1080p']}/{total} clips)"
            )
            return res_1080p
        logger.info(f"Auto resolution: 720p {orientation_str} (default)")
        return res_720p

    def detect_best_resolution(self, clips: list[AssemblyClip]) -> tuple[int, int]:
        resolution_counts: dict[str, int] = {"4k": 0, "1080p": 0, "720p": 0, "other": 0}
        orientation_counts: dict[str, int] = {"portrait": 0, "landscape": 0}

        for clip in clips:
            res = self.get_video_resolution(clip.path)
            if not res:
                continue
            w, h = res
            max_dim = max(w, h)
            orientation_counts["portrait" if h > w else "landscape"] += 1
            if max_dim >= 2160:
                resolution_counts["4k"] += 1
            elif max_dim >= 1080:
                resolution_counts["1080p"] += 1
            elif max_dim >= 720:
                resolution_counts["720p"] += 1
            else:
                resolution_counts["other"] += 1

        total = len(clips)
        if total == 0:
            logger.info("No clips to analyze, defaulting to 1080p landscape")
            return (1920, 1080)

        is_portrait = orientation_counts["portrait"] > orientation_counts["landscape"]
        orientation_str = "portrait" if is_portrait else "landscape"
        logger.info(
            f"Orientation: {orientation_str} "
            f"({orientation_counts['portrait']} portrait, {orientation_counts['landscape']} landscape)"
        )

        if is_portrait:
            res_4k, res_1080p, res_720p = (2160, 3840), (1080, 1920), (720, 1280)
        else:
            res_4k, res_1080p, res_720p = (3840, 2160), (1920, 1080), (1280, 720)

        return self.pick_resolution_tier(
            resolution_counts, total, orientation_str, res_4k, res_1080p, res_720p
        )

    def probe_framerate(self, path: Path) -> float:
        try:
            fps = self.probe_cache.get(path).fps
            if fps > 0:
                return fps
        except (OSError, ProbeError, ValueError) as e:
            logger.warning(f"Failed to probe framerate of {path}: {e}")
        return 60.0  # Default fallback

    def has_audio_stream(self, path: Path) -> bool:
        try:
            probe = self.probe_cache.get(path)
            if not probe.has_audio:
                logger.debug(f"No audio stream in {path.name}")
                return False
            logger.debug("Audio stream in %s: codec=%s", path.name, probe.audio_codec)
            return True
        except (OSError, ProbeError, ValueError) as e:
            logger.warning(f"Error checking audio stream for {path.name}: {e}")
            return False

    def audio_bitrate(self, path: Path) -> int:
        """Return the first audio stream bitrate, or zero when unavailable."""
        try:
            return self.probe_cache.get(path).audio_bitrate
        except (OSError, ProbeError, ValueError) as exc:
            logger.debug("Failed to detect audio bitrate for %s: %s", path, exc)
            return 0

    def detect_framerate(self, video_path: Path) -> float | None:
        return probe_rate(self.probe_cache, video_path)

    def detect_max_framerate(self, clips: list[AssemblyClip]) -> int:
        """The film's frame rate, from its videos (`film_frame_rate`)."""
        return film_frame_rate(clips, self.detect_framerate)

    def estimate_duration(self, clips: list[AssemblyClip]) -> float:
        """Estimate final duration, accounting for transition overlaps."""
        if not clips:
            return 0.0

        total = sum(clip.duration for clip in clips)

        # Subtract transition overlaps
        if self.settings.transition == TransitionType.CROSSFADE and len(clips) > 1:
            overlap = self.settings.effective_transition_duration * (len(clips) - 1)
            total -= overlap

        return max(0, total)


# A film with no video has no rate of its own to follow.
FILM_WITHOUT_VIDEO_FPS = 30


# Footage at or above this rate is slow motion: it plays slowed down, so it is a 30 fps film.
SLOW_MOTION_FPS = 100
# From here a clip is fast footage that wants a 50 or 60 fps film.
FAST_FOOTAGE_FPS = 45


def film_frame_rate(clips: list[AssemblyClip], rate_of: Callable[[Path], float | None]) -> int:
    """The film's frame rate: 30, unless most of its video seconds are 50/60 fps footage.

    Every per-frame stage costs in proportion to the rate, so one fast clip does not
    set the rate of the whole film. Slow motion (recorded at 100 fps or more, played
    slowed) counts as 30. A film made only of 24 or 25 fps footage keeps that rate
    rather than stretching to 30 with judder. Title screens and photos are excluded:
    both are rendered at whatever rate the film picks. A film with no video plays at 30.
    """

    footage = [
        (fps, max(clip.duration, 0.0))
        for clip in clips
        if not getattr(clip, "is_title_screen", False) and not getattr(clip, "is_photo", False)
        if (fps := rate_of(clip.path))
    ]
    if not footage:
        return FILM_WITHOUT_VIDEO_FPS
    fast = [(fps, secs) for fps, secs in footage if FAST_FOOTAGE_FPS <= fps < SLOW_MOTION_FPS]
    if sum(secs for _fps, secs in fast) * 2 > sum(secs for _fps, secs in footage):
        return 60 if max(fps for fps, _secs in fast) >= 55 else 50
    # WHY (#2348): 24 and 25 fps libraries were stretched to 30 with judder.
    slowest_ceiling = max(fps for fps, _secs in footage)
    if slowest_ceiling < 27.5:
        return 25 if slowest_ceiling >= 24.5 else 24
    return 30


def probe_rate(probe_cache: ProbeCache, video_path: Path) -> float | None:
    """A video's frame rate, or None when it cannot be read."""
    try:
        return probe_cache.get(video_path).fps or None
    except (OSError, ProbeError, ValueError) as e:
        logger.debug(f"Failed to detect frame rate: {e}")
    return None
