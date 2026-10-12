"""Scaling and aspect ratio utilities."""

from __future__ import annotations

import logging
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from immich_memories.analysis.subject_framing import FaceBox

if TYPE_CHECKING:  # cv2 is imported lazily at every call site below
    import cv2

__all__ = [
    "_get_aspect_ratio_filter",
    "_get_smart_crop_filter",
    "aggregate_mood_from_clips",
    "detect_faces_in_video",
    "smart_crop_window",
]

logger = logging.getLogger(__name__)

# Bundled rather than downloaded; provenance and licence sit next to it.
_YUNET_MODEL = Path(__file__).parent / "bundled_models" / "face_detection_yunet_2023mar.onnx"
# OpenCV's own FaceDetectorYN documentation and sample use these three.
_YUNET_SCORE_THRESHOLD = 0.9
_YUNET_NMS_THRESHOLD = 0.3
_YUNET_TOP_K = 5000


def _get_aspect_ratio_filter(
    clip_index: int,
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    face_center: tuple[float, float] | None,
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
    - "smart_zoom": Smart crop centered on face
    - "black_bars": Simple letterbox/pillarbox with black bars

    Args:
        clip_index: Index of clip (for unique labels)
        src_w: Source video width
        src_h: Source video height
        target_w: Target output width
        target_h: Target output height
        face_center: Tuple of (x, y) normalized 0-1 or None (used for smart_zoom)
        pix_fmt: Pixel format for output
        target_fps: Target frame rate
        rotation_filter: Optional rotation filter prefix (e.g., "transpose=1,")
        hdr_conversion: Optional HDR conversion filter
        colorspace_filter: Optional colorspace filter
        output_suffix: Suffix for output label (default "scaled")
        scale_mode: "blur", "smart_zoom", or "black_bars"

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

    if scale_mode == "smart_zoom" and face_center is not None:
        # Smart crop centered on face
        crop_filter = _get_smart_crop_filter(
            src_w, src_h, target_w, target_h, face_center[0], face_center[1]
        )
        return (
            f"[{clip_index}:v]{rotation_filter}setpts=PTS-STARTPTS,"
            f"{crop_filter},"
            f"{common_suffix}{output_label}"
        )

    # Default: Blur background (Instagram-style)
    # Also used when smart_zoom is selected but no face is found
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


def _smart_crop_size(src_w: int, src_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    """The largest crop of the source with the target's aspect ratio."""
    target_ar = target_w / target_h
    if src_w / src_h > target_ar:
        return int(src_h * target_ar), src_h
    return src_w, int(src_w / target_ar)


def smart_crop_window(src_w: int, src_h: int, target_w: int, target_h: int) -> tuple[float, float]:
    """The share of the source's width and height the smart-zoom crop keeps."""
    crop_w, crop_h = _smart_crop_size(src_w, src_h, target_w, target_h)
    return crop_w / src_w, crop_h / src_h


def _get_smart_crop_filter(
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
    face_center_x: float,
    face_center_y: float,
) -> str:
    """Generate FFmpeg crop filter centered on face position.

    Calculates the optimal crop region that:
    1. Maintains the target aspect ratio
    2. Centers on the detected face position
    3. Stays within source video bounds

    Args:
        src_w: Source video width
        src_h: Source video height
        target_w: Target output width
        target_h: Target output height
        face_center_x: Face center X position (normalized 0-1, left to right)
        face_center_y: Face center Y position (normalized 0-1, top to bottom)

    Returns:
        FFmpeg filter string for crop and scale (e.g., "crop=1080:1920:100:50,scale=1080:1920")
    """
    crop_w, crop_h = _smart_crop_size(src_w, src_h, target_w, target_h)

    # Convert normalized face position to pixels
    face_x = int(face_center_x * src_w)
    face_y = int(face_center_y * src_h)

    # Center crop on face with bounds checking
    crop_x = max(0, min(face_x - crop_w // 2, src_w - crop_w))
    crop_y = max(0, min(face_y - crop_h // 2, src_h - crop_h))

    return f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}:flags=lanczos"


def _init_face_detector() -> object | None:
    """Initialize face detector: Apple Vision (preferred) or OpenCV.

    Returns:
        VisionFaceDetector instance, or None to signal OpenCV fallback.
        Raises ImportError if neither is available.
    """
    try:
        from immich_memories.analysis.apple_vision import VisionFaceDetector

        return VisionFaceDetector()
    except (ImportError, RuntimeError):
        # ImportError: pyobjc not installed; RuntimeError: not on macOS
        import cv2  # noqa: F401

        return None  # Will use OpenCV directly


def _get_video_duration(video_path: Path) -> float:
    """Probe video duration using ffprobe, falling back to 10s."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return 10.0


def _extract_frame(video_path: Path, sample_time: float) -> Path | None:
    """Extract a single video frame to a temp JPEG file."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        frame_path = Path(tmp.name)

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(sample_time),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
        capture_output=True,
        timeout=30,
    )
    return frame_path if frame_path.exists() else None


def _anonymous_face(x1: float, y1: float, x2: float, y2: float) -> FaceBox:
    """A detected face nobody is matched to, clamped to its frame."""
    return FaceBox(
        x1=min(1.0, max(0.0, x1)),
        y1=min(1.0, max(0.0, y1)),
        x2=min(1.0, max(0.0, x2)),
        y2=min(1.0, max(0.0, y2)),
        named=False,
    )


def _detect_faces_vision(detector: object, frame_path: Path) -> list[FaceBox]:
    """Detect faces using Apple Vision and return their normalized boxes."""
    import cv2

    img = cv2.imread(str(frame_path))
    if img is None:
        return []
    # Vision's boxes have their origin at the bottom left; ours at the top left.
    return [
        _anonymous_face(face.x, 1.0 - face.y - face.height, face.x + face.width, 1.0 - face.y)
        for face in detector.detect_faces(img)
    ]


@lru_cache(maxsize=1)
def _yunet_detector() -> cv2.FaceDetectorYN:
    """Build the YuNet detector once — each create() re-reads and re-parses the graph.

    The input size is a placeholder: every call resets it to the frame it is
    about to read, because YuNet's anchors are laid out for the exact size.
    """
    import cv2

    return cv2.FaceDetectorYN.create(
        str(_YUNET_MODEL),
        "",
        (320, 320),
        _YUNET_SCORE_THRESHOLD,
        _YUNET_NMS_THRESHOLD,
        _YUNET_TOP_K,
    )


def _detect_faces_opencv(frame_path: Path) -> list[FaceBox]:
    """Detect faces with OpenCV's YuNet and return their normalized boxes."""
    import cv2

    img = cv2.imread(str(frame_path))
    if img is None:
        return []
    h, w = img.shape[:2]
    detector = _yunet_detector()
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)
    if faces is None:
        return []
    # YuNet answers float32; plain floats keep numpy types out of the framing maths.
    boxes = faces[:, :4].astype(float).tolist()
    return [_anonymous_face(x / w, y / h, (x + fw) / w, (y + fh) / h) for x, y, fw, fh in boxes]


def detect_faces_in_video(video_path: Path) -> tuple[FaceBox, ...]:
    """Every face a detector finds in three frames across the video, normalized 0-1.

    Nobody is matched to these faces: a detector finds faces, not people. Uses
    Apple Vision on macOS (GPU-accelerated) with OpenCV's YuNet as the fallback.
    """
    try:
        detector = _init_face_detector()
    except ImportError:
        logger.debug("No face detection available (Apple Vision or OpenCV)")
        return ()

    duration = _get_video_duration(video_path)
    sample_times = [duration * p for p in (0.2, 0.5, 0.8)]
    found: list[FaceBox] = []

    for sample_time in sample_times:
        try:
            frame_path = _extract_frame(video_path, sample_time)
            if frame_path is None:
                continue

            if detector is not None:
                found.extend(_detect_faces_vision(detector, frame_path))
            else:
                found.extend(_detect_faces_opencv(frame_path))

            frame_path.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
            logger.debug(f"Face detection failed for frame at {sample_time}s: {e}")
            continue

    logger.debug(f"Detected {len(found)} faces in {video_path.name}")
    return tuple(found)


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
