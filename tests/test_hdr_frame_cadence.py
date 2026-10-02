"""Only agreed lower source rates may defer duplication past HDR conversion."""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from immich_memories.processing.clip_caption import ClipCaption
from immich_memories.processing.streaming_frame_decoder import (
    FrameDecoder,
    _matching_stream_rate,
    _source_properties,
    make_decoder,
)


@pytest.mark.parametrize(
    ("rate", "privacy", "conversion", "deferred"),
    [
        (Fraction(30), False, "zscale=t=smpte2084", True),
        (Fraction(30000, 1001), False, "zscale=t=smpte2084", True),
        (Fraction(30), True, "zscale=t=smpte2084", False),
        (None, False, "zscale=t=smpte2084", False),
        (Fraction(60), False, "zscale=t=smpte2084", False),
        (Fraction(240), False, "zscale=t=smpte2084", False),
        (Fraction(0), False, "zscale=t=smpte2084", False),
        (Fraction(30), False, "", False),
    ],
)
def test_conversion_work_is_not_duplicated_but_caption_grid_stays_final(
    tmp_path, rate, privacy, conversion, deferred
):
    decoder = FrameDecoder(
        tmp_path / "source.mov",
        2160,
        3840,
        60,
        pix_fmt="yuv420p10le",
        source_frame_rate=rate,
        privacy_blur=privacy,
        hdr_conversion=conversion,
        output_pix_fmt=",format=p010le",
        caption=ClipCaption(date="1 October"),
        caption_window=(30, 120),
    )
    filters = decoder._build_vf()
    assert filters.count("fps=60") == 1
    assert (filters.index("format=p010le") < filters.index("fps=60")) == deferred
    assert filters.index("fps=60") < filters.index("drawtext=")
    assert "gte(n,30)*lt(n,120)" in filters


@pytest.mark.parametrize(
    ("average", "nominal", "expected"),
    [
        ("30/1", "30/1", Fraction(30)),
        ("30000/1001", "30000/1001", Fraction(30000, 1001)),
        ("30/1", "60/1", None),
        ("1155600/4811", "240/1", None),
        (None, "30/1", None),
        ("0/0", "30/1", None),
        ("broken", "30/1", None),
        ("0/1", "0/1", None),
        ("-30/1", "-30/1", None),
    ],
)
def test_ambiguous_or_unusable_stream_rates_keep_the_original_order(average, nominal, expected):
    probe = SimpleNamespace(average_frame_rate=average, nominal_frame_rate=nominal)
    assert _matching_stream_rate(probe) == expected


def test_hdr_to_sdr_keeps_the_original_conversion_order(tmp_path):
    decoder = FrameDecoder(
        tmp_path / "source.mov",
        1080,
        1920,
        60,
        pix_fmt="rgb24",
        source_frame_rate=Fraction(30),
        hdr_conversion="zscale=t=linear,tonemap=hable,zscale=t=bt709",
    )
    filters = decoder._build_vf()
    assert filters.index("fps=60") < filters.index("tonemap=hable")


def test_a_failed_probe_keeps_the_original_order(monkeypatch, tmp_path):
    from immich_memories.processing.probe_cache import ProbeError

    def unavailable(*_args):
        raise ProbeError("unavailable")

    monkeypatch.setattr("immich_memories.processing.probe_cache.ProbeCache.get", unavailable)
    assert _source_properties(tmp_path / "source.mov") == (None, None)


def test_decoder_geometry_and_cadence_share_one_probe(monkeypatch, tmp_path):
    reads = []
    probe = SimpleNamespace(
        resolution=(1080, 1920), average_frame_rate="30/1", nominal_frame_rate="30/1"
    )

    def read(_cache, path):
        reads.append(path)
        return probe

    monkeypatch.setattr("immich_memories.processing.probe_cache.ProbeCache.get", read)
    path = tmp_path / "source.mov"
    context = SimpleNamespace(hdr_type="sdr", clip_hdr_types=[None])
    decoder = make_decoder(SimpleNamespace(path=path), 0, 2160, 3840, 60, ctx=context)
    assert reads == [path]
    assert decoder._source_size == (1080, 1920)
    assert decoder._source_frame_rate == Fraction(30)


def test_invalid_rate_retains_probed_geometry(monkeypatch, tmp_path):
    probe = SimpleNamespace(
        resolution=(1080, 1920), average_frame_rate="invalid", nominal_frame_rate="30/1"
    )
    monkeypatch.setattr("immich_memories.processing.probe_cache.ProbeCache.get", lambda *_a: probe)
    assert _source_properties(tmp_path / "source.mov") == ((1080, 1920), None)


@pytest.mark.parametrize(
    ("rate", "privacy", "early"),
    [
        (Fraction(120), False, True),
        (Fraction(120), True, False),
        (Fraction(60), False, True),
        (None, False, False),
    ],
)
def test_known_equal_and_high_rates_normalize_before_spatial_work(tmp_path, rate, privacy, early):
    decoder = FrameDecoder(
        tmp_path / "source.mov",
        2160,
        3840,
        60,
        source_frame_rate=rate,
        privacy_blur=privacy,
        scale_mode="blur",
    )
    filters = decoder._build_vf()
    assert filters.count("fps=60") == 1
    assert (filters.index("fps=60") < filters.index("scale=")) == early
