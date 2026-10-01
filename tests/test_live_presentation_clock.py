"""MOV presentation survives older FFprobe duration guesses without losing samples."""

import hashlib
import json
import subprocess
from fractions import Fraction

import pytest

from immich_memories.processing.probe_cache import (
    PRESENTATION_POLICY,
    PresentationIntegrityError,
    ProbeCache,
    ProbeError,
)


@pytest.fixture
def reordered_mov(tmp_path, monkeypatch):
    source = tmp_path / "reordered.mov"
    source.write_bytes(b"compressed-source")
    visible = [0, 20, 40, 60]
    stream = {
        "index": 0,
        "codec_type": "video",
        "codec_name": "hevc",
        "width": 160,
        "height": 120,
        "time_base": "1/600",
        "start_pts": 0,
        "duration_ts": 140,
        "duration": str(140 / 600),
        "nb_frames": "5",
        "avg_frame_rate": "120/7",
        "r_frame_rate": "30/1",
        "nb_read_frames": "4",
    }
    commands = []
    packets = [{"pts": pts, "dts": pts - 40, "duration": 20, "flags": "___"} for pts in visible] + [
        {"pts": 140, "dts": 100, "duration": 20, "flags": "_D_"}
    ]
    response = {
        "frames": [{"pts": pts} for pts in visible],
        "packets": packets,
        "stream": stream,
        "error": "",
        "during_decode": lambda: None,
    }

    def probe(command, **_kwargs):
        # WHY: exercise the public probe cache against the FFprobe process
        # boundary. Older MOV demuxers guess duration on reordered samples.
        commands.append(command)
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "ffprobe version 7.1.5-fixture\n", "")
        payload = {"streams": [stream]}
        if "-show_packets" in command:
            payload["packets"] = response["packets"]
        elif "-show_frames" in command:
            response["during_decode"]()
            payload["frames"] = response["frames"]
        else:
            payload["format"] = {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "duration": str(140 / 600),
            }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), response["error"])

    monkeypatch.setattr(subprocess, "run", probe)
    return source, response, commands


def test_complete_mov_uses_its_visible_edit_end_instead_of_guessed_packet_duration(reordered_mov):
    source, _response, commands = reordered_mov
    cache = ProbeCache()

    segment = cache.quantized_segment(source, 0.0, 140 / 600, Fraction(30))

    assert segment["frames"] == 7
    assert segment["kept_packets"] == 4
    assert segment["eof_pts"] == 140
    assert cache.last_video_frame(source)["duration_ticks"] == 80
    assert cache.quantized_segment(source, 0.0, 140 / 600, Fraction(30)) == segment
    assert sum("-show_frames" in command for command in commands) == 1
    proof = cache.complete_video_presentation(source)
    assert proof["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert proof["decoder_identity"] == "ffprobe version 7.1.5-fixture"
    assert proof["presentation_policy"] == PRESENTATION_POLICY
    assert proof["video_stream_index"] == 0
    assert proof["video_compressed_packets"] == 5
    assert proof["video_visible_packets"] == proof["video_decoded_frames"] == 4
    assert proof["video_discarded_pts"] == [140]


def test_source_change_during_certification_cannot_bind_old_samples_to_new_bytes(reordered_mov):
    source, response, _commands = reordered_mov
    response["packets"][-2]["duration"] = 80
    response["during_decode"] = lambda: source.write_bytes(b"changed-compressed-source")

    with pytest.raises(ProbeError, match="changed during presentation certification"):
        ProbeCache().complete_video_presentation(source)


def test_complete_final_display_interval_does_not_require_a_reference_at_the_endpoint(
    reordered_mov,
):
    source, response, _commands = reordered_mov
    response["packets"].pop()
    response["stream"]["nb_frames"] = "4"
    cache = ProbeCache()

    segment = cache.quantized_segment(source, 0.0, 140 / 600, Fraction(30))

    assert segment["frames"] == 7
    proof = cache.complete_video_presentation(source)
    assert proof["video_discarded_pts"] == []
    assert proof["video_decoded_frames"] == proof["video_compressed_packets"] == 4
    assert proof["video_end_ticks"] == 140


@pytest.mark.parametrize("invalid", ["backwards", "missing", "duplicate", "decoder-error"])
def test_positive_invalid_media_evidence_is_typed_and_bound_to_exact_bytes(reordered_mov, invalid):
    source, response, _commands = reordered_mov
    if invalid == "backwards":
        response["frames"][1:3] = reversed(response["frames"][1:3])
    elif invalid == "missing":
        response["frames"].pop(1)
        response["stream"]["nb_read_frames"] = "3"
    elif invalid == "duplicate":
        response["packets"][1]["pts"] = 0
    else:
        response["error"] = "[hevc] Could not find ref with POC 10"

    with pytest.raises(PresentationIntegrityError) as caught:
        ProbeCache().complete_video_presentation(source)

    evidence = dict(caught.value.evidence)
    assert evidence["reason"] == caught.value.reason
    assert evidence["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert evidence["video_stream_index"] == 0
    assert evidence["decoder_identity"] == "ffprobe version 7.1.5-fixture"
    assert evidence["presentation_policy"] == PRESENTATION_POLICY


def test_unavailable_metadata_never_becomes_a_persistable_corrupt_verdict(reordered_mov):
    source, response, _commands = reordered_mov
    response["stream"].pop("nb_frames")
    with pytest.raises(ProbeError) as caught:
        ProbeCache().complete_video_presentation(source)
    assert not isinstance(caught.value, PresentationIntegrityError)


def test_decoder_timeout_never_becomes_a_persistable_corrupt_verdict(reordered_mov):
    source, response, _commands = reordered_mov
    response["packets"][-2]["duration"] = 80

    def timeout():
        raise subprocess.TimeoutExpired("ffprobe", 30)

    response["during_decode"] = timeout
    with pytest.raises(ProbeError) as caught:
        ProbeCache().complete_video_presentation(source)
    assert not isinstance(caught.value, PresentationIntegrityError)
