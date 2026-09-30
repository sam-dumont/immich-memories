"""Certify a complete video track and the actual audio samples beyond its edit end."""

import json
import subprocess
from fractions import Fraction

from immich_memories.processing.probe_cache import ProbeError


def _decoded(path, selector: str) -> tuple[dict, list[dict]]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", selector,
            "-count_frames", "-show_frames", "-show_entries",
            "stream=index,time_base,start_pts,duration_ts,nb_frames,nb_read_frames,sample_rate:"
            "frame=pts,nb_samples", "-of", "json", str(path),
        ], capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    if result.returncode or result.stderr.strip():
        raise ProbeError("Audio-tail source did not decode completely")
    data = json.loads(result.stdout)
    (stream,) = data["streams"]
    frames = data["frames"]
    if not frames:
        raise ProbeError("Audio-tail source has no decoded frames")
    return stream, frames


def _complete_video(path, probe, tail) -> dict:
    stream, frames = _decoded(path, str(probe.video_stream_index))
    clock = Fraction(stream["time_base"])
    declared = int(stream["nb_frames"])
    points = [frame["pts"] for frame in frames]
    endpoint = (int(stream.get("start_pts", 0)) + int(stream["duration_ts"])) * clock
    packet_end = (tail["pts"] + tail["duration_ticks"]) * Fraction(tail["time_base"])
    if (
        declared <= 0
        or declared != len(frames)
        or int(stream["nb_read_frames"]) != declared
        or len(set(points)) != declared
        or max(points) != tail["pts"]
        or clock <= 0
        or endpoint != packet_end
    ):
        raise ProbeError("Audio-tail video samples disagree with their visible endpoint")
    return {
        "video_declared_frames": declared,
        "video_decoded_frames": len(frames),
        "video_end_ticks": int(stream.get("start_pts", 0)) + int(stream["duration_ts"]),
        "video_time_base": str(clock),
        "video_end_seconds": float(endpoint) - probe.container_start_seconds,
    }


def _complete_audio(path, origin: float, start: float, end: float) -> dict:
    stream, frames = _decoded(path, "a:0")
    clock, rate = Fraction(stream["time_base"]), int(stream["sample_rate"])
    if clock <= 0 or rate <= 0:
        raise ProbeError("Audio-tail source has no sample clock")
    position = first = Fraction(frames[0]["pts"]) * clock
    samples = 0
    for frame in frames:
        count = frame["nb_samples"]
        if type(count) is not int or count <= 0 or Fraction(frame["pts"]) * clock != position:
            raise ProbeError("Audio-tail decoded samples have a gap or corrupt interval")
        samples += count
        position += Fraction(count, rate)
    source_origin = Fraction(str(origin))
    visible_start = int(stream.get("start_pts", 0)) * clock
    visible_end = visible_start + int(stream["duration_ts"]) * clock
    covered_start, covered_end = max(first, visible_start), min(position, visible_end)
    if (
        visible_end <= visible_start
        or covered_start > Fraction(str(start)) + source_origin
        or covered_end < Fraction(str(end)) + source_origin
    ):
        raise ProbeError("Decoded audio does not cover the selected audio-tail interval")
    return {
        "audio_stream_index": stream["index"],
        "audio_time_base": str(clock),
        "audio_sample_rate": rate,
        "audio_decoded_samples": samples,
        "audio_start_seconds": float(covered_start - source_origin),
        "audio_end_seconds": float(covered_end - source_origin),
        "audio_visible_end_ticks": int(stream.get("start_pts", 0)) + int(stream["duration_ts"]),
        "audio_visible_end_seconds": float(visible_end - source_origin),
        "audio_decoded_end_ticks": str(position / clock),
        "audio_decoded_end_seconds": float(position - source_origin),
    }


def certify_audio_tail(path, entry, probe, tail) -> dict:
    """No container-duration allowance: complete video and decoded audio authorize this hold."""
    try:
        if not probe.has_audio:
            raise ProbeError("Audio-tail source has no audio")
        video = _complete_video(path, probe, tail)
        if not entry.start < video["video_end_seconds"] < entry.end:
            raise ProbeError("Audio-tail interval must retain real visible video")
        audio = _complete_audio(path, probe.container_start_seconds, entry.start, entry.end)
        return (
            video
            | audio
            | {
                "boundary": "complete-video-with-decoded-audio-tail",
                "hold_seconds": entry.end - video["video_end_seconds"],
                "selected_end_seconds": entry.end,
            }
        )
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError) as exc:
        raise ProbeError("Source has no verified complete-video audio tail") from exc
