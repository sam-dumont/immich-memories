"""A kept clip's picture and sound facts: measured once, at a fixed cost (#1949)."""

import shutil

import numpy as np
import pytest

from immich_memories.analysis.editorial_clip_facts import ClipWindowFacts
from immich_memories.analysis.editorial_video_windows import place_windows
from immich_memories.speech.models import SpeechRegion
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset
from tests.test_frame_activity import shout

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


class Loud:
    """Hears 'speech' wherever the sound is loud: the tone stands in for a voice."""

    available = True

    def detect(self, pcm, rate):
        return self.detect_with_music(pcm, rate)[0]

    def detect_with_music(self, pcm, rate):
        loud = np.flatnonzero(np.abs(pcm) > 0.1)
        if not len(loud):
            return [], 0.0
        return [SpeechRegion(loud[0] / rate, loud[-1] / rate)], 0.0


def test_a_long_clip_plays_where_someone_talks_and_is_heard_once(tmp_path):
    data = shout(tmp_path / "talk.mp4", seconds=120.0, loud=(12.0, 16.0))
    assets = {"v": make_asset("v")}
    reads = []

    def facts():
        # WHY: Immich's playback range endpoint is the boundary replaced (and the speech
        # model, by `Loud`); the index, the sound fetch and its decode run for real.
        def read(asset_id, start, length):
            reads.append(length)
            return data[start : start + length], len(data)

        return ClipWindowFacts(assets=assets, store=annotation_store(), read=read, detector=Loud())

    first = facts()
    [carrier] = place_windows(
        [{"kind": "video", "asset_id": "v", "seconds": 6.0, "raw_seconds": 120.0}], first
    )
    first.flush()

    assert carrier["start_time"] <= 12.0 and carrier["end_time"] >= 15.5
    assert first.speech_for("v"), "the speech the window was chosen on is kept for the cut"
    # A minute of a 2-minute clip, read straight through (frame-interleaved sound is
    # hundreds of seeks otherwise); never the clip.
    assert sum(reads) < 0.6 * len(data)

    measured = len(reads)
    again = facts()
    place_windows([{"kind": "video", "asset_id": "v", "seconds": 6.0, "raw_seconds": 120.0}], again)
    assert len(reads) == measured, "the next film reads the bank"


class MusicStub:
    """A detector that hears half its span as music, regardless of content (#1951)."""

    available = True

    def detect(self, pcm, rate):
        return []

    def detect_with_music(self, pcm, rate):
        return [], 0.5


def test_music_fraction_is_measured_and_then_banked(tmp_path):
    data = shout(tmp_path / "talk.mp4", seconds=10.0, loud=(2.0, 4.0))
    assets = {"v": make_asset("v")}
    reads = []

    def facts():
        def read(asset_id, start, length):
            reads.append(length)
            return data[start : start + length], len(data)

        return ClipWindowFacts(
            assets=assets, store=annotation_store(), read=read, detector=MusicStub()
        )

    first = facts()
    [carrier] = place_windows(
        [{"kind": "video", "asset_id": "v", "seconds": 4.0, "raw_seconds": 10.0}], first
    )
    first.flush()

    assert first.music_fraction_for("v") == 0.5

    measured = len(reads)
    again = facts()
    place_windows([{"kind": "video", "asset_id": "v", "seconds": 4.0, "raw_seconds": 10.0}], again)
    assert len(reads) == measured, "the bank answers the music fraction too"
    assert again.music_fraction_for("v") == 0.5
