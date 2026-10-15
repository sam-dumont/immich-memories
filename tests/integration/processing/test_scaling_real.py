"""Real FFmpeg integration tests for scaling utilities.

Tests aggregate_mood_from_clips.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group("ffmpeg")]


# ---------------------------------------------------------------------------
# aggregate_mood_from_clips
# ---------------------------------------------------------------------------


class TestAggregateMoodFromClips:
    def test_returns_dominant_mood(self):
        from immich_memories.processing.scaling_utilities import (
            aggregate_mood_from_clips,
        )

        clips = [
            SimpleNamespace(llm_emotion="happy"),
            SimpleNamespace(llm_emotion="joyful"),
            SimpleNamespace(llm_emotion="calm"),
            SimpleNamespace(llm_emotion="happy"),
        ]
        result = aggregate_mood_from_clips(clips)
        # "happy" and "joyful" both map to "happy" (3 total), "calm" has 1
        assert result == "happy"

    def test_returns_none_for_empty(self):
        from immich_memories.processing.scaling_utilities import (
            aggregate_mood_from_clips,
        )

        clips = [SimpleNamespace(other_attr="x")]
        assert aggregate_mood_from_clips(clips) is None

    def test_handles_unknown_emotions(self):
        from immich_memories.processing.scaling_utilities import (
            aggregate_mood_from_clips,
        )

        clips = [
            SimpleNamespace(llm_emotion="mysterious"),
            SimpleNamespace(llm_emotion="mysterious"),
        ]
        # Unknown emotions pass through unmapped
        result = aggregate_mood_from_clips(clips)
        assert result == "mysterious"
