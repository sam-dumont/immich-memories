"""Whether this machine's hardware decoder gives the software decoder's picture.

A clip goes to the hardware decoder only because its frames, repacked, are the
software decoder's frames. A decoder that breaks that would put its error into
every clip: VideoToolbox on a virtual Mac hands back H.264 chroma up to 188
ten-bit codes away from the software decode, with the luma untouched. So a short
known clip is decoded both ways, once a process for each codec, format and set
of hwaccel arguments, and a mismatch keeps that codec in software.
"""

from __future__ import annotations

import functools
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# The software encoder that writes the known clip, by the codec names the
# hardware gate uses.
_ENCODERS = {"h264": "libx264", "h265": "libx265"}
_PROBE_SOURCE = "testsrc2=size=320x240:rate=30"
_PROBE_FRAMES = "3"
_TIMEOUT_SECONDS = 30


def _ffmpeg(arguments: list[str]) -> bytes | None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *arguments]
    try:
        result = subprocess.run(  # noqa: S603 - fixed program, arguments from this module
            command,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Decoder check could not run: %s", exc)
        return None
    return result.stdout if result.returncode == 0 else None


def _decoded(clip: Path, hwaccel_args: tuple[str, ...], pixel_format: str) -> bytes | None:
    """Every frame of ``clip``, repacked the way the clip decoder repacks hardware frames."""
    return _ffmpeg(
        [*hwaccel_args, "-i", str(clip), "-vf", f"format={pixel_format}", "-f", "rawvideo", "-"]
    )


@functools.cache
def hardware_decode_matches(hwaccel_args: tuple[str, ...], codec: str, pixel_format: str) -> bool:
    """Whether ``hwaccel_args`` decode ``codec`` in ``pixel_format`` to the software frames.

    False when the frames differ, and when the check cannot run at all (no
    software encoder for the known clip, a decoder that fails): the clip is then
    decoded in software, which is always right.
    """
    encoder = _ENCODERS.get(codec)
    if encoder is None:
        return False
    with tempfile.TemporaryDirectory(prefix="immich-memories-decode-check-") as folder:
        clip = Path(folder) / f"known.{codec}.mp4"
        encoded = _ffmpeg(
            ["-f", "lavfi", "-i", _PROBE_SOURCE, "-frames:v", _PROBE_FRAMES,
             "-c:v", encoder, "-pix_fmt", pixel_format, "-y", str(clip)]
        )  # fmt: skip
        if encoded is None:
            logger.info("No %s clip to check the hardware decoder on; decoding in software", codec)
            return False
        hardware = _decoded(clip, hwaccel_args, pixel_format)
        software = _decoded(clip, (), pixel_format)
    if hardware is None or software is None or hardware != software:
        logger.info(
            "The hardware decoder's %s %s frames do not match the software decoder's; "
            "decoding %s in software",
            codec,
            pixel_format,
            codec,
        )
        return False
    return True
