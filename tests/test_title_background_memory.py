"""CPU backgrounds release resolution-sized scratch after returning a picture."""

import gc
import hashlib
import tracemalloc

import pytest

from immich_memories.titles import backgrounds, backgrounds_animated
from immich_memories.titles.backgrounds import create_gradient_background


def test_rendering_new_sizes_does_not_retain_full_frame_scratch():
    # Warm imports and Pillow before measuring allocations owned by the renders.
    create_gradient_background(17, 13, ["#123456", "#abcdef"])
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for width, height in [(651, 367), (367, 651)]:
            image = create_gradient_background(width, height, ["#123456", "#abcdef"])
            assert image.size == (width, height)
            del image
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()

    # These two small pictures used to retain 3.6 MiB of coordinate planes.
    assert retained < 512 * 1024, f"Background scratch retained {retained} bytes"


# Raw RGB hashes captured from f31a1c5ca before the coordinate-storage change.
# Small odd dimensions cover both orientations without encoder rounding noise.
@pytest.mark.parametrize(
    ("renderer", "arguments", "expected"),
    [
        (
            backgrounds.create_gradient_background,
            (97, 61, ["#123456", "#abcdef"], 32.5),
            "8af67b40e6448fc7210642e0036d543e11e6fc67d84ffbeefef9cbfe8fa6193b",
        ),
        (
            backgrounds.create_gradient_background,
            (61, 97, ["#123456", "#eeeeee", "#ff11cc"], 135),
            "982ba8f4157649e017c991a355b2920e06d0a2c6059a27172044e0fe5673ee9b",
        ),
        (
            backgrounds.create_radial_gradient,
            (97, 61, "#123456", "#000000"),
            "7d56039e291f3eb32b234ac5e6dfb235a2519b298e3a62d51a867adefcf7cb28",
        ),
        (
            backgrounds.create_vignette_background,
            (61, 97, "#111111", "#ffeecc"),
            "0f48a1e63e290a577d95213f513e242eb21412c2f79184050df46f50675ed614",
        ),
        (
            backgrounds_animated.create_animated_gradient,
            (97, 61, ["#112233", "#557799"], 135, 0.37),
            "9e84e156eb021f6abddca0f05917e66f03e429bdab1b7fda560c8814dc610d25",
        ),
        (
            backgrounds_animated.create_animated_radial,
            (61, 97, "#112233", "#557799", 0.37),
            "1f6c83f0fecfd347b49483b811117f0eabd61344490e4d649967b8785e08a762",
        ),
        (
            backgrounds_animated.create_animated_vignette,
            (97, 61, "#112233", "#557799", 0.37),
            "5a50fee107334ccd36761d02c970336c030ed5a542894754f1e823fa98190a15",
        ),
    ],
)
def test_cpu_background_pixels_match_the_previous_renderer(renderer, arguments, expected):
    image = renderer(*arguments)
    assert hashlib.sha256(image.tobytes()).hexdigest() == expected
