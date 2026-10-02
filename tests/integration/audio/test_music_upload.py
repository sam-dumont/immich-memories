"""Uploaded soundtracks are checked with the installed FFmpeg tools."""

import subprocess

import pytest

from tests.generated_audio_fixtures import write_audio
from tests.web_api_fixtures import api_client, config_in

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("suffix", [".wav", ".mp3", ".m4a"])
def test_a_real_soundtrack_round_trips_through_upload_and_playback(tmp_path, suffix):
    source = tmp_path / "source.wav"
    write_audio(source, 0.1)
    track = tmp_path / f"soundtrack{suffix}"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), str(track)], check=True, timeout=20)
    client = api_client(config_in(tmp_path))
    uploaded = client.post("/api/v1/music", files={"file": (track.name, track.read_bytes())})
    assert uploaded.status_code == 201
    played = client.get(f"/api/v1/music/{uploaded.json()['id']}")
    assert played.content == track.read_bytes()


def test_an_mp4_container_without_audio_is_not_a_soundtrack(tmp_path):
    track = tmp_path / "silent.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=16x16:d=0.1",
            "-an",
            "-c:v",
            "mpeg4",
            "-f",
            "mp4",
            str(track),
        ],
        check=True,
        timeout=20,
    )
    client = api_client(config_in(tmp_path))
    response = client.post("/api/v1/music", files={"file": (track.name, track.read_bytes())})
    assert response.status_code == 422
