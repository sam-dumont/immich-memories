"""Regenerate `singing_excerpt_16k.npy`, a real-audio fixture for #1951 (music/singing).

Source: "Twinkle Twinkle Little Star - sung with full lyrics.ogg", by Commons user
Dcoetzee, https://commons.wikimedia.org/wiki/File:Twinkle_Twinkle_Little_Star_-_sung_with_full_lyrics.ogg
Licence: CC0 1.0 Universal (public domain dedication),
https://creativecommons.org/publicdomain/zero/1.0/deed.en -- no attribution required,
and the recording is of the uploader singing a traditional nursery rhyme a cappella, so it
contains no identifiable third party and no personal data about anyone in this project.

This is real sung audio (the AED head's "singing" and "music" columns both answer to it),
unlike `synthetic_speech_16k.npy`'s synthesised voice, so the two fixtures together prove
the detector tells recorded singing apart from a model of plain speech.

Run with `python tests/fixtures/speech/generate_singing_excerpt.py` to refetch and
re-trim it (needs network access and ffmpeg).

Layout: 3.0 s, starting 3.0 s into the source (past its lyric-free intro), downsampled
to 16 kHz mono and stored as int16 PCM, matching `synthetic_speech_16k.npy`'s format.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

SOURCE_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/4/4f/"
    "Twinkle_Twinkle_Little_Star_-_sung_with_full_lyrics.ogg"
)
START_S = 3.0
DURATION_S = 3.0
SAMPLE_RATE = 16000
OUTPUT = Path(__file__).parent / "singing_excerpt_16k.npy"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source.ogg"
        pcm = Path(directory) / "excerpt.pcm"
        subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-o", str(source), SOURCE_URL], check=True
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(START_S),
                "-t",
                str(DURATION_S),
                "-i",
                str(source),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-f",
                "s16le",
                str(pcm),
            ],
            check=True,
            capture_output=True,
        )
        audio = np.fromfile(pcm, dtype="<i2")
    np.save(OUTPUT, audio)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
