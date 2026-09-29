"""Small deterministic waveforms for generation boundary tests."""

from pathlib import Path

import numpy as np


def write_audio(path: Path, amplitude: float) -> None:
    import wave

    samples = amplitude * np.sin(2 * np.pi * 440 * np.arange(24000) / 24000)
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes((samples * 32767).astype("<i2").tobytes())
