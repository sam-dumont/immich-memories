"""Only complete video and contiguous visible audio can authorize a measured hold."""

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.processing.live_audio_tail import certify_audio_tail
from immich_memories.processing.live_material import LiveSourceEntry
from immich_memories.processing.probe_cache import ProbeError


@pytest.fixture
def decoded_source(monkeypatch):
    video = {
        "streams": [
            {
                "index": 0,
                "time_base": "1/30",
                "start_pts": 0,
                "duration_ts": 2,
                "nb_frames": "2",
                "nb_read_frames": "2",
            }
        ],
        "frames": [{"pts": 0}, {"pts": 1}],
    }
    audio = {
        "streams": [
            {
                "index": 1,
                "time_base": "1/48000",
                "sample_rate": "48000",
                "start_pts": 0,
                "duration_ts": 4096,
            }
        ],
        "frames": [{"pts": 0, "nb_samples": 2048}, {"pts": 2048, "nb_samples": 2048}],
    }
    response = {"video": copy.deepcopy(video), "audio": copy.deepcopy(audio), "error": ""}

    def decode(command, **_kwargs):
        # WHY: simulate independently decoded source metadata at the FFprobe
        # process boundary. Complete AV integration tests exercise real decoding.
        selector = command[command.index("-select_streams") + 1]
        payload = response["video" if selector == "0" else "audio"]
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), response["error"])

    monkeypatch.setattr(subprocess, "run", decode)
    return response


def _certify():
    return certify_audio_tail(
        Path("source.mov"),
        LiveSourceEntry("still", "video", 0.0, 0.0, 0.08),
        SimpleNamespace(has_audio=True, video_stream_index=0, container_start_seconds=0.0),
        {"pts": 1, "duration_ticks": 1, "time_base": "1/30"},
    )


def test_a_complete_source_records_actual_samples_and_visible_endpoints(decoded_source):
    proof = _certify()
    assert proof["video_decoded_frames"] == proof["video_declared_frames"] == 2
    assert proof["audio_decoded_samples"] == 4096
    assert proof["audio_visible_end_ticks"] == 4096
    assert proof["selected_end_seconds"] == 0.08
    assert proof["hold_seconds"] == pytest.approx(0.08 - 2 / 30)


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-video-sample",
        "video-end-disagreement",
        "duplicate-video-pts",
        "audio-gap",
        "short-visible-audio",
        "decoder-error",
        "empty-decode",
        "missing-clock",
    ],
)
def test_source_corruption_cannot_become_a_longer_frame_hold(decoded_source, invalid):
    video, audio = decoded_source["video"], decoded_source["audio"]
    if invalid == "missing-video-sample":
        video["streams"][0]["nb_frames"] = "3"
    elif invalid == "video-end-disagreement":
        video["streams"][0]["duration_ts"] = 3
    elif invalid == "duplicate-video-pts":
        video["frames"][0]["pts"] = 1
    elif invalid == "audio-gap":
        audio["frames"][1]["pts"] = 2050
    elif invalid == "short-visible-audio":
        audio["streams"][0]["duration_ts"] = 3000
    elif invalid == "decoder-error":
        decoded_source["error"] = "corrupt compressed sample"
    elif invalid == "empty-decode":
        video["frames"] = []
    else:
        audio["streams"][0].pop("time_base")
    with pytest.raises(ProbeError):
        _certify()
