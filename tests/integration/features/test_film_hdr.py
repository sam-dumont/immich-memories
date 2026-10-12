"""A photo saved with an HDR gain map, in an HDR film and tone-mapped into an SDR one."""

from __future__ import annotations

import pytest

from tests.e2e.fake_library import CARRIERS
from tests.features.cli_harness import UserHome, basic_config
from tests.integration.features.cuts import story_of
from tests.integration.features.film_probe import (
    luma_levels,
    luma_percentile,
    video_stream,
)
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import (
    QUIET_DAY,
    one_day,
    render,
    render_into,
    the_day_only,
)

# A day of one still saved with an HDR gain map (the fixture's `hdr` photo).
HDR_DAY = the_day_only(lambda p: p.hdr)
# The PQ code of diffuse white (203 nits) in a 10-bit film: HDR highlights sit above it.
_PQ_DIFFUSE_WHITE = 572
# Legal white of 8-bit limited-range video.
_LEGAL_WHITE = 235


@pytest.mark.feature("hdr.end-to-end")
def test_a_gain_mapped_photo_keeps_hdr_in_an_hdr_h265_film_and_is_tone_mapped_in_sdr(
    library_home: UserHome, immich: LibraryServer, tmp_path
):
    still = next(p for p in CARRIERS if p.day == HDR_DAY)
    home = UserHome(tmp_path / "hdr-home")
    config = basic_config(immich.base_url, immich.api_key, home)
    config["output"].update(codec="h265", hdr_mode="auto")
    home.write_config(config)

    hdr = render(home, *one_day(HDR_DAY, "--no-music"))
    plain = render(home, *one_day(QUIET_DAY, "--no-music"))
    sdr = render_into(library_home, tmp_path / "sdr", *one_day(HDR_DAY, "--no-music"))

    assert still.hdr
    stream = video_stream(hdr.film)
    assert (stream["codec_name"], stream["pix_fmt"], stream["color_transfer"]) == (
        "hevc",
        "yuv420p10le",
        "smpte2084",
    )
    middle = story_of(home, hdr.run_id)[0]
    _, peak = luma_levels(hdr.film, middle.middle)
    assert peak > _PQ_DIFFUSE_WHITE + 40, peak
    # The same settings with a plain photo stay SDR: the gain map is what made the film HDR.
    assert video_stream(plain.film)["color_transfer"] == "bt709"
    # An SDR film tone-maps it: BT.709, 8 bits, and no dimmer than the picture itself.
    sdr_stream = video_stream(sdr.film)
    assert (sdr_stream["codec_name"], sdr_stream["color_transfer"]) == ("h264", "bt709")
    shot = story_of(library_home, sdr.run_id)[0]
    mean, _ = luma_levels(sdr.film, shot.middle)
    picture_mean, _ = luma_levels(still.source, 0, convert="format=yuv420p")
    assert mean > 0.9 * picture_mean, (mean, picture_mean)
    # Tone-mapped into legal range: H.264 rings a few codes past 235 at hard edges, so the
    # brightest pixel is no measure (236 and 241 on real-Immich runs); the picture's own
    # highlights are. 99.5 % of the frame stays at or under legal white.
    assert luma_percentile(sdr.film, shot.middle, 99.5) <= _LEGAL_WHITE
