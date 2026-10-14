"""Short test videos whose soundtrack is one of the speech fixtures (tests/fixtures/speech)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

SPEECH_FIXTURES = Path(__file__).parent / "fixtures" / "speech"
SPOKEN = "synthetic_speech_16k.npy"
SUNG = "singing_excerpt_16k.npy"


def video_with_sound(path: Path, fixture_name: str) -> Path:
    """A 3 s 160x90 H.264 clip carrying the fixture's 16 kHz audio as AAC."""
    audio = np.load(SPEECH_FIXTURES / fixture_name).astype(np.float32) / 32768.0
    subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=30:d=3",
            "-f",
            "f32le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "1",
            "-c:a",
            "aac",
            str(path),
        ],
        input=audio.tobytes(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path
