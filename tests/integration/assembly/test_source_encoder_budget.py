"""Memory-bounded source workers retain the requested HDR output."""

import json
import subprocess
from contextlib import nullcontext

import numpy as np
import pytest

from immich_memories.processing import memory_budget
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.source_preparation import prepare_sources
from immich_memories.processing.streaming_assembler import StreamingEncoder

pytestmark = pytest.mark.integration


def test_budgeted_source_workers_preserve_hdr_frames(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text(f"{4 * 2**30}\n")
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    plan = EncodingPlan(
        OutputCodec.H265, "libx265", ("-preset", "veryfast", "-crf", "20"),
        HdrTransfer.PQ, False, "yuv420p10le", "mp4",
    )  # fmt: skip
    width, height = 1152, 1920
    frame = np.full((height * 3 // 2, width), 512, dtype=np.uint16)

    def encode(_client, index):
        output = tmp_path / f"source-{index}.mp4"
        encoder = StreamingEncoder(output, width, height, 30, plan)
        encoder.start()
        for _ in range(6):
            encoder.write_frame(frame)
        encoder.finish()
        return output

    outputs = list(
        prepare_sources(
            [0, 1],
            client=lambda: nullcontext(None),
            prepare=encode,
            workers=2,
        )
    )
    assert len(outputs) == 2
    for _index, output in outputs:
        stream = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_streams", "-of", "json", str(output),
        ]))["streams"][0]  # fmt: skip
        assert (stream["width"], stream["height"]) == (width, height)
        assert stream["pix_fmt"] == "yuv420p10le"
        assert stream["color_transfer"] == "smpte2084"
        assert int(stream["nb_read_frames"]) == 6
        assert float(stream["duration"]) == 0.2
