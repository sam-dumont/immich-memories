"""A merged Live Photo burst is encoded under a plan, not a hardcoded encoder (#504).

The merge runs at download time, before the run's own EncodingPlan exists. The
plan keeps the burst's transfer and makes the merge lossless, so the film's own
encode is the only lossy step a Live Photo takes (#2692).
"""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities
from immich_memories.processing.live_photo_merger import build_merge_command


def _apple() -> HWAccelCapabilities:
    return HWAccelCapabilities(
        backend=HWAccelBackend.APPLE,
        supports_h264_encode=True,
        supports_h265_encode=True,
    )


def _nvidia() -> HWAccelCapabilities:
    return HWAccelCapabilities(
        backend=HWAccelBackend.NVIDIA,
        supports_h264_encode=True,
        supports_h265_encode=True,
        supports_h264_decode=True,
        supports_h265_decode=True,
    )


def _merge_command(
    *,
    is_hdr: bool = False,
    hardware_enabled: bool = True,
    capabilities: HWAccelCapabilities | None = None,
    clip: Path = Path("a.mov"),
) -> list[str]:
    caps = capabilities if capabilities is not None else HWAccelCapabilities()
    # WHY: build_merge_command probes the file and the host encoder; a.mov never exists.
    with (
        # WHY: the audio ffprobe boundary.
        patch(
            "immich_memories.processing.live_photo_merger.probe_clip_has_audio",
            return_value=False,
        ),
        # WHY: the HDR ffprobe boundary.
        patch(
            "immich_memories.processing.live_photo_merger._detect_clip_hdr",
            return_value=is_hdr,
        ),
        # WHY: the FFmpeg encoder probe, so the assertions do not depend on the
        # machine running the tests.
        patch(
            "immich_memories.processing.burst_encoding.detect_hardware_acceleration",
            return_value=caps,
        ),
    ):
        return build_merge_command(
            [clip],
            [(0.0, 1.0)],
            Path("out.mp4"),
            hardware_enabled=hardware_enabled,
        )


def _encoder(cmd: list[str]) -> str:
    return cmd[cmd.index("-c:v") + 1]


def test_the_burst_is_lossless_so_the_film_encode_is_its_only_lossy_step() -> None:
    """The film decodes the merge and encodes it again (#2692): a lossy merge was a
    second generation, and a quality dial nobody had written down (#504)."""
    cmd = _merge_command()

    assert cmd[cmd.index("-qp") + 1] == "0"
    assert "-crf" not in cmd


def test_a_mac_merges_losslessly_in_software() -> None:
    """VideoToolbox has no lossless mode; x264 at its fastest preset costs a Live
    Photo about a second of CPU against twenty for the libx265 merge it replaces."""
    assert _encoder(_merge_command(capabilities=_apple())) == "libx264"


@pytest.mark.parametrize(
    ("is_hdr", "encoder", "pixel_format"),
    [(False, "h264_nvenc", "yuv420p"), (True, "hevc_nvenc", "p010le")],
)
def test_an_nvidia_machine_merges_losslessly_on_the_card(is_hdr, encoder, pixel_format) -> None:
    """NVENC's lossless mode decodes back to exactly its input (#2760), so the merge
    leaves the CPU without becoming a second lossy generation."""
    cmd = _merge_command(is_hdr=is_hdr, capabilities=_nvidia())

    assert _encoder(cmd) == encoder
    assert cmd[cmd.index("-tune") + 1] == "lossless"
    assert cmd[cmd.index("-pix_fmt") + 1] == pixel_format
    assert "-qp" not in cmd
    assert "-cq" not in cmd


def test_each_part_of_a_burst_is_decoded_on_the_gpu() -> None:
    """A hardware decoder gives back the software decoder's frames (#2709)."""
    clip = Path(__file__).parent / "fixtures" / "hdr_samples" / "dolby_vision_84.mov"

    cmd = _merge_command(is_hdr=True, capabilities=_nvidia(), clip=clip)

    assert cmd.index("-hwaccel") < cmd.index("-i")
    assert cmd[cmd.index("-hwaccel") + 1] == "cuda"
    assert "-hwaccel_output_format" not in cmd


def test_a_burst_without_hardware_decodes_in_software() -> None:
    clip = Path(__file__).parent / "fixtures" / "hdr_samples" / "dolby_vision_84.mov"

    assert "-hwaccel" not in _merge_command(is_hdr=True, hardware_enabled=False, clip=clip)


def test_disabling_hardware_is_still_honoured() -> None:
    """The probe is process-wide, but the user's switch still decides."""
    assert _encoder(_merge_command(capabilities=_apple(), hardware_enabled=False)) == "libx264"


def test_no_hardware_available_falls_back_to_software() -> None:
    assert _encoder(_merge_command()) == "libx264"


@pytest.mark.parametrize("hardware_enabled", [True, False])
def test_an_hdr_burst_keeps_its_hlg_metadata_and_ten_bits(hardware_enabled: bool) -> None:
    """The merged file is an intermediate the assembler still has to read as HDR.
    Losing the transfer here would tone-map the burst before anything chose to."""
    cmd = _merge_command(is_hdr=True, capabilities=_apple(), hardware_enabled=hardware_enabled)

    assert cmd[cmd.index("-color_trc") + 1] == "arib-std-b67"
    assert cmd[cmd.index("-color_primaries") + 1] == "bt2020"
    assert cmd[cmd.index("-colorspace") + 1] == "bt2020nc"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
    assert cmd[cmd.index("-qp") + 1] == "0"


def test_the_download_path_carries_the_setting_into_the_merge() -> None:
    """The plan is only worth resolving if the run's switch reaches it: the merge
    happens under the downloader, several hops from where the config is read."""
    from immich_memories.generate_downloads import _try_merge_burst

    clips = [Path("a.mov"), Path("b.mov")]
    trims = [(0.0, 1.5), (0.0, 1.5)]  # 3.0 s: over the 2.5 s motion floor

    # WHY: _try_merge_burst validates, builds, and runs FFmpeg; a.mov and b.mov are names only.
    with (
        # WHY: the ffprobe validation of files that do not exist on disk.
        patch(
            "immich_memories.processing.live_photo_merger.filter_valid_clips",
            return_value=(clips, trims),
        ),
        # WHY: the unit under test is what gets asked for, not the command itself.
        patch(
            "immich_memories.processing.live_photo_merger.build_merge_command",
            return_value=["ffmpeg"],
        ) as build,
        # WHY: replaces the FFmpeg run.
        patch(
            "immich_memories.generate_downloads.subprocess.run",
            return_value=CompletedProcess(["ffmpeg"], 1, stdout="", stderr="fixture failure"),
        ),
    ):
        _try_merge_burst(clips, trims, Path("out.mp4"), hardware_enabled=False)

    assert build.call_args.kwargs["hardware_enabled"] is False


def test_a_merge_that_fails_on_the_card_runs_again_in_software() -> None:
    """A driver or session limit must not cost the Live Photo its motion."""
    from immich_memories.generate_downloads import _try_merge_burst

    clips = [Path("a.mov"), Path("b.mov")]
    trims = [(0.0, 1.5), (0.0, 1.5)]

    def ffmpeg(command, **_kwargs):
        return CompletedProcess(command, 1, stdout="", stderr="encoder failed")

    # WHY: _try_merge_burst validates, builds, and runs FFmpeg; a.mov and b.mov are names only.
    with (
        # WHY: the ffprobe validation of files that do not exist on disk.
        patch(
            "immich_memories.processing.live_photo_merger.filter_valid_clips",
            return_value=(clips, trims),
        ),
        # WHY: what gets asked for is under test, not the command itself.
        patch(
            "immich_memories.processing.live_photo_merger.build_merge_command",
            return_value=["ffmpeg"],
        ) as build,
        # WHY: replaces the FFmpeg runs; both fail, so both attempts are visible.
        patch("immich_memories.generate_downloads.subprocess.run", side_effect=ffmpeg),
    ):
        assert _try_merge_burst(clips, trims, Path("out.mp4"), hardware_enabled=True) is None

    assert [call.kwargs["hardware_enabled"] for call in build.call_args_list] == [True, False]
