"""The HDR cadence optimization preserves decoded pixels and the final clock."""

from __future__ import annotations

import subprocess
from fractions import Fraction

import pytest

from immich_memories.processing.clip_caption import ClipCaption
from immich_memories.processing.hdr_utilities import get_hdr_conversion_filter
from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize(
    ("fill", "rate", "transfer"),
    [
        ("black", "30", "hlg"),
        ("blur", "30", "hlg"),
        ("blur", "30000/1001", "hlg"),
        ("blur", "30", "sdr"),
    ],
)
def test_hdr_duplication_after_conversion_keeps_seek_caption_and_frame_hashes(
    tmp_path, fill, rate, transfer
):
    source = tmp_path / "source.mkv"
    source_hdr = transfer == "hlg"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=128x72:rate={rate}:duration=1.5",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "yuv420p10le" if source_hdr else "yuv420p",
            "-color_primaries",
            "bt2020" if source_hdr else "bt709",
            "-colorspace",
            "bt2020nc" if source_hdr else "bt709",
            "-color_trc",
            "arib-std-b67" if source_hdr else "bt709",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    hashes = []
    conversion = get_hdr_conversion_filter(transfer, "pq", required=True)
    for source_rate in (None, Fraction(rate)):
        decoder = FrameDecoder(
            source,
            72,
            128,
            60,
            pix_fmt="yuv420p10le",
            input_seek=0.25,
            hdr_conversion=conversion if source_hdr else "",
            sdr_to_hdr_filter="" if source_hdr else conversion.removeprefix(","),
            colorspace_filter=",setparams=colorspace=bt2020nc:color_primaries=bt2020:color_trc=smpte2084",
            output_pix_fmt=",format=p010le",
            scale_mode=fill,
            source_size=(128, 72),
            source_frame_rate=source_rate,
            caption=ClipCaption(date="1 October"),
            caption_window=(3, 30),
        )
        chain = decoder._build_vf()
        filters = (
            ["-filter_complex", f"[0:v]{chain}[out]", "-map", "[out]"]
            if decoder._use_filter_complex
            else ["-vf", chain]
        )
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "2",
                "-ss",
                "0.25",
                "-i",
                str(source),
                *filters,
                "-an",
                "-t",
                "1",
                "-pix_fmt",
                "yuv420p10le",
                "-r",
                "60",
                "-f",
                "framemd5",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        hashes.append(result.stdout)
    assert hashes[0] == hashes[1]
    assert len([line for line in hashes[0].splitlines() if line.startswith(b"0,")]) == 60
