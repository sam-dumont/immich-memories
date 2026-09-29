"""Technical validity gate for generated music, before mastering can amplify it."""

import subprocess
from pathlib import Path

import numpy as np


def validate_generated_audio(path: Path) -> str | None:
    """Return a safe failure reason, or None for finite, audible decoded audio.

    Keep every channel at its native rate: downmixing can cancel valid stereo,
    and resampling can hide non-finite samples. A -80 dBFS peak floor rejects
    numerical noise while allowing quiet introductions and musical rests.
    """
    try:
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-"],
            capture_output=True,
            timeout=120,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "audio could not be decoded"
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    if not samples.size:
        return "audio contains no samples"
    if not np.isfinite(samples).all():
        return "audio contains non-finite samples"
    if np.max(np.abs(samples)) <= 0.0001:
        return "audio is silent or near-silent (peak <= -80 dBFS)"
    return None
