"""A collage is no picture of this life; an ordinary photograph is (forwarded copies).

A real lockdown film let through a collage app's page: six photos tiled under a text title.
The check reads the thin flat gutters running between textured tiles, across and down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.analysis.forwarded_copy_checks import composed_in_words, looks_composed
from tests.test_forwarded_fallback import _collage_jpeg

LIBRARY = Path(__file__).parent / "e2e" / "fixtures" / "library"


def test_a_collage_page_reads_as_composed():
    assert looks_composed(_collage_jpeg())


def _photographs() -> list[Path]:
    """Every twentieth picture of the fixture library: real photographs, streets and facades
    with flat painted bands, skies over horizons, a waterfall beside a dark edge."""
    pictures = sorted(LIBRARY.rglob("*.jpg"))
    return pictures[::20]


@pytest.mark.parametrize("picture", _photographs(), ids=lambda path: path.name)
def test_an_ordinary_photograph_never_reads_as_composed(picture: Path):
    assert not looks_composed(picture.read_bytes())


@pytest.mark.parametrize(
    "picture",
    ["north-0715-0124.jpg", "north-0728-0799.jpg", "north-0728-0803.jpg"],
)
def test_a_facade_or_a_dark_edge_is_no_gutter(picture: str):
    """The photographs an earlier draft of the check called collages."""
    assert not looks_composed(next(LIBRARY.rglob(picture)).read_bytes())


def test_a_caption_names_a_picture_made_rather_than_taken():
    assert composed_in_words("A collage of six photos under a title") == "collage"
    assert composed_in_words("A child superimposed on a glitter background") == "superimposed"
    assert composed_in_words("Two children on a hay bale under a grey sky") is None


def test_unreadable_bytes_are_no_collage():
    assert not looks_composed(b"not an image")
