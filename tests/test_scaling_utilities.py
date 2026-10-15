"""Tests for scaling_utilities — FFmpeg filter strings and mood aggregation."""

from __future__ import annotations

from types import SimpleNamespace

from immich_memories.processing.scaling_utilities import (
    _get_aspect_ratio_filter,
    aggregate_mood_from_clips,
)

# ---------------------------------------------------------------------------
# TestGetAspectRatioFilter
# ---------------------------------------------------------------------------


class TestGetAspectRatioFilter:
    """Verify FFmpeg filter strings for each scale mode."""

    def test_similar_aspect_ratio_simple_scale(self):
        """When src and target AR differ < 5%, use simple scale (no crop/blur)."""
        result = _get_aspect_ratio_filter(0, 1920, 1080, 1920, 1080)
        assert "scale=1920:1080" in result
        assert "boxblur" not in result
        assert "crop=" not in result
        assert "pad=" not in result

    def test_portrait_in_landscape_blur_mode(self):
        """Portrait (1080x1920) in landscape (1920x1080) with blur background."""
        result = _get_aspect_ratio_filter(0, 1080, 1920, 1920, 1080, scale_mode="blur")
        assert "boxblur" in result
        assert "overlay" in result
        assert "split" in result
        # Background fills target dimensions
        assert "scale=1920:1080" in result

    def test_landscape_in_portrait_blur_mode(self):
        """Landscape in portrait target with blur background."""
        result = _get_aspect_ratio_filter(0, 1920, 1080, 1080, 1920, scale_mode="blur")
        assert "boxblur" in result
        assert "overlay" in result

    def test_black_bars_mode(self):
        """Black bars mode pads with black, no blur."""
        result = _get_aspect_ratio_filter(0, 1080, 1920, 1920, 1080, scale_mode="black_bars")
        assert "pad=1920:1080" in result
        assert "boxblur" not in result
        assert "black" in result

    def test_clip_index_in_labels(self):
        """Clip index appears in FFmpeg stream labels."""
        result = _get_aspect_ratio_filter(5, 1080, 1920, 1920, 1080)
        # Blur mode uses labels like bg5, fg5, blurred5, scaled5
        assert "bg5" in result
        assert "fg5" in result
        assert "[v5scaled]" in result

    def test_rotation_filter_prepended(self):
        """Rotation filter is prepended to the pipeline."""
        result = _get_aspect_ratio_filter(0, 1920, 1080, 1920, 1080, rotation_filter="transpose=1,")
        assert "transpose=1," in result

    def test_hdr_conversion_included(self):
        """HDR conversion filter is included in the pipeline."""
        result = _get_aspect_ratio_filter(
            0, 1920, 1080, 1920, 1080, hdr_conversion=",zscale=t=bt709"
        )
        assert "zscale=t=bt709" in result

    def test_fps_and_format_in_output(self):
        """fps, format, and setsar are always in the filter."""
        result = _get_aspect_ratio_filter(
            0, 1920, 1080, 1920, 1080, pix_fmt="yuv420p", target_fps=30
        )
        assert "fps=30" in result
        assert "format=yuv420p" in result
        assert "setsar=1" in result

    def test_output_suffix_in_label(self):
        """Custom output suffix appears in the output label."""
        result = _get_aspect_ratio_filter(0, 1080, 1920, 1920, 1080, output_suffix="custom")
        assert "[v0custom]" in result

    def test_default_blur_mode(self):
        """Default scale mode is blur when AR differs significantly."""
        result = _get_aspect_ratio_filter(0, 1080, 1920, 1920, 1080)
        assert "boxblur" in result

    def test_colorspace_filter_included(self):
        """Colorspace filter appears in common suffix."""
        result = _get_aspect_ratio_filter(
            0, 1920, 1080, 1920, 1080, colorspace_filter=",colorspace=bt709"
        )
        assert "colorspace=bt709" in result


# ---------------------------------------------------------------------------
# TestAggregateMood
# ---------------------------------------------------------------------------


class TestAggregateMood:
    """Verify mood aggregation from clip emotions."""

    @staticmethod
    def _make_clip(emotion: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(llm_emotion=emotion)

    def test_empty_clips_returns_none(self):
        assert aggregate_mood_from_clips([]) is None

    def test_no_emotions_returns_none(self):
        clips = [self._make_clip(None), self._make_clip(None)]
        assert aggregate_mood_from_clips(clips) is None

    def test_single_emotion_returned(self):
        clips = [self._make_clip("happy")]
        assert aggregate_mood_from_clips(clips) == "happy"

    def test_dominant_mood_wins(self):
        clips = [
            self._make_clip("happy"),
            self._make_clip("happy"),
            self._make_clip("calm"),
        ]
        assert aggregate_mood_from_clips(clips) == "happy"

    def test_emotion_mapped_to_mood(self):
        """'joyful' maps to 'happy' mood category."""
        clips = [self._make_clip("joyful")]
        assert aggregate_mood_from_clips(clips) == "happy"

    def test_case_insensitive(self):
        clips = [self._make_clip("HAPPY")]
        assert aggregate_mood_from_clips(clips) == "happy"

    def test_unknown_emotion_passed_through(self):
        """Unknown emotions are used as-is (not mapped)."""
        clips = [self._make_clip("mysterious")]
        assert aggregate_mood_from_clips(clips) == "mysterious"

    def test_mixed_mapped_emotions(self):
        """Multiple emotions in the same family all map to one mood."""
        clips = [
            self._make_clip("joyful"),
            self._make_clip("cheerful"),
            self._make_clip("calm"),
        ]
        # joyful->happy, cheerful->happy, calm->calm -> happy wins (2 vs 1)
        assert aggregate_mood_from_clips(clips) == "happy"

    def test_empty_string_emotion_ignored(self):
        """Empty string emotions are falsy and should be skipped."""
        clips = [self._make_clip(""), self._make_clip("calm")]
        assert aggregate_mood_from_clips(clips) == "calm"

    def test_all_mood_families_mapped(self):
        """Spot-check one member from each mood family."""
        families = {
            "delighted": "happy",
            "serene": "calm",
            "excited": "energetic",
            "fun": "playful",
            "sentimental": "nostalgic",
            "loving": "romantic",
            "quiet": "peaceful",
            "thrilling": "exciting",
        }
        for emotion, expected_mood in families.items():
            clips = [self._make_clip(emotion)]
            assert aggregate_mood_from_clips(clips) == expected_mood, (
                f"{emotion} should map to {expected_mood}"
            )
