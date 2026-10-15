"""Scaling and aspect ratio utilities."""

from __future__ import annotations

import logging
from collections import Counter

__all__ = [
    "_get_aspect_ratio_filter",
    "aggregate_mood_from_clips",
]

logger = logging.getLogger(__name__)


def _get_aspect_ratio_filter(
    clip_index: int,
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    pix_fmt: str = "yuv420p",
    target_fps: int = 60,
    rotation_filter: str = "",
    hdr_conversion: str = "",
    colorspace_filter: str = "",
    output_suffix: str = "scaled",
    scale_mode: str = "blur",
) -> str:
    """Generate FFmpeg filter for aspect ratio handling.

    Handles portrait/landscape mismatch with different modes:
    - "blur": Blur background (Instagram-style)
    - "black_bars": Simple letterbox/pillarbox with black bars

    Args:
        clip_index: Index of clip (for unique labels)
        src_w: Source video width
        src_h: Source video height
        target_w: Target output width
        target_h: Target output height
        pix_fmt: Pixel format for output
        target_fps: Target frame rate
        rotation_filter: Optional rotation filter prefix (e.g., "transpose=1,")
        hdr_conversion: Optional HDR conversion filter
        colorspace_filter: Optional colorspace filter
        output_suffix: Suffix for output label (default "scaled")
        scale_mode: "blur" or "black_bars"

    Returns:
        FFmpeg filter string.
    """
    output_label = f"[v{clip_index}{output_suffix}]"
    common_suffix = f"fps={target_fps},settb=1/{target_fps},format={pix_fmt}{hdr_conversion}{colorspace_filter},setsar=1"

    # Check if aspect ratios are significantly different (>5% difference)
    src_ar = src_w / src_h
    target_ar = target_w / target_h
    ar_diff = abs(src_ar - target_ar) / max(src_ar, target_ar)

    if ar_diff < 0.05:
        # Aspect ratios are similar - simple scale
        return (
            f"[{clip_index}:v]{rotation_filter}setpts=PTS-STARTPTS,"
            f"scale={target_w}:{target_h}:flags=lanczos,"
            f"{common_suffix}{output_label}"
        )

    # Handle different scale modes
    if scale_mode == "black_bars":
        # Simple letterbox/pillarbox with black bars (no blur)
        return (
            f"[{clip_index}:v]{rotation_filter}setpts=PTS-STARTPTS,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"{common_suffix}{output_label}"
        )

    # Default: Blur background (Instagram-style)
    bg_label = f"bg{clip_index}"
    fg_label = f"fg{clip_index}"
    blurred_label = f"blurred{clip_index}"
    scaled_label = f"scaled{clip_index}"

    return (
        f"[{clip_index}:v]{rotation_filter}setpts=PTS-STARTPTS,split[{bg_label}][{fg_label}];"
        f"[{bg_label}]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},boxblur=luma_radius=150:chroma_radius=150:luma_power=3:chroma_power=3[{blurred_label}];"
        f"[{fg_label}]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos[{scaled_label}];"
        f"[{blurred_label}][{scaled_label}]overlay=(W-w)/2:(H-h)/2,"
        f"{common_suffix}{output_label}"
    )


def aggregate_mood_from_clips(clips: list) -> str | None:
    """Aggregate the dominant mood from a list of clips.

    Analyzes the llm_emotion from each clip and returns the most common mood.
    Maps various emotion labels to the mood categories used by title screens.

    Args:
        clips: List of clips with llm_emotion attributes.

    Returns:
        Dominant mood string (e.g., "happy", "calm") or None if no emotions found.
    """
    # Mapping from LLM emotion labels to title screen mood categories
    emotion_to_mood = {
        # Happy family
        "happy": "happy",
        "joyful": "happy",
        "cheerful": "happy",
        "delighted": "happy",
        "content": "happy",
        # Calm family
        "calm": "calm",
        "serene": "calm",
        "relaxed": "calm",
        "tranquil": "calm",
        # Energetic family
        "energetic": "energetic",
        "excited": "energetic",
        "enthusiastic": "energetic",
        "dynamic": "energetic",
        # Playful family
        "playful": "playful",
        "fun": "playful",
        "silly": "playful",
        "mischievous": "playful",
        # Nostalgic family
        "nostalgic": "nostalgic",
        "sentimental": "nostalgic",
        "wistful": "nostalgic",
        # Romantic family
        "romantic": "romantic",
        "loving": "romantic",
        "tender": "romantic",
        "affectionate": "romantic",
        # Peaceful family
        "peaceful": "peaceful",
        "quiet": "peaceful",
        "gentle": "peaceful",
        # Exciting family
        "exciting": "exciting",
        "thrilling": "exciting",
        "adventurous": "exciting",
    }

    # Collect emotions from clips
    emotions = []
    for clip in clips:
        emotion = getattr(clip, "llm_emotion", None)
        if emotion:
            # Normalize and map to mood category
            emotion_lower = emotion.lower().strip()
            mood = emotion_to_mood.get(emotion_lower, emotion_lower)
            emotions.append(mood)

    if not emotions:
        return None

    # Count and return most common
    mood_counts = Counter(emotions)
    dominant_mood, count = mood_counts.most_common(1)[0]

    logger.info(f"Dominant mood from {len(emotions)} clips: {dominant_mood} ({count} occurrences)")
    return dominant_mood
