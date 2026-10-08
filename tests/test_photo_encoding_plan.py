"""Photo intermediates spend HDR encoding only on HDR sources in an HDR film."""

import pytest

from immich_memories.config_loader import Config
from immich_memories.photos.encoding import photo_encoding_plan
from immich_memories.processing.encoding_plan import HdrTransfer, OutputCodec


def test_hdr_photo_in_sdr_film_uses_software_h264():
    config = Config(hardware={"enabled": False}, output={"codec": "h264"})

    plan = photo_encoding_plan(config, transfer=HdrTransfer.PQ)

    assert plan.codec is OutputCodec.H264
    assert plan.encoder == "libx264"
    assert plan.target_transfer is HdrTransfer.NONE
    assert plan.tone_map_to_sdr
    assert plan.crf == 18


@pytest.mark.parametrize("hdr_mode", ["auto", "hdr"])
def test_gain_mapped_photo_in_hdr_film_preserves_pq(hdr_mode):
    config = Config(hardware={"enabled": False}, output={"codec": "h265", "hdr_mode": hdr_mode})

    plan = photo_encoding_plan(config, transfer=HdrTransfer.PQ)

    assert plan.codec is OutputCodec.H265
    assert plan.target_transfer is HdrTransfer.PQ
    assert not plan.tone_map_to_sdr


def test_sdr_photo_in_hdr_film_keeps_an_sdr_intermediate():
    config = Config(hardware={"enabled": False}, output={"codec": "h265", "hdr_mode": "hdr"})

    plan = photo_encoding_plan(config, transfer=HdrTransfer.NONE)

    assert plan.encoder == "libx264"
    assert plan.target_transfer is HdrTransfer.NONE
    assert plan.crf == 18


@pytest.mark.parametrize(("hdr_mode", "policy"), [("hdr", "prefer_hardware"), ("auto", "strict")])
def test_explicit_hdr_film_does_not_lose_photo_hdr_on_h264_only_hardware(hdr_mode, policy):
    from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities

    config = Config(
        tier="basic", output={"codec": "h265", "hdr_mode": hdr_mode, "codec_policy": policy}
    )
    capabilities = HWAccelCapabilities(backend=HWAccelBackend.VAAPI, supports_h264_encode=True)

    plan = photo_encoding_plan(config, transfer=HdrTransfer.PQ, capabilities=capabilities)

    assert plan.encoder == "libx265"
    assert plan.target_transfer is HdrTransfer.PQ
