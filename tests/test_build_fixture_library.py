"""The demo library build keeps each file's own place and time, and only CC0 or CC BY files."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_fixture_library.py"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_fixture_library", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-07-12 08:33:06", "2025-07-12T08:33:06"),
        ("2017:08:05 14:20", "2017-08-05T14:20:00"),
        ("23 August 2014, 14:54:43", "2014-08-23T14:54:43"),
        ("Taken on 11 February 2006, 22:24", "2006-02-11T22:24:00"),
        ('<time class="dtstart" datetime="2018-07-04">4 July 2018</time>', None),
        ("", None),
    ],
)
def test_a_capture_time_is_read_only_when_the_file_holds_one(build, value, expected) -> None:
    assert build.parse_taken(value) == expected


def test_a_shift_moves_whole_days_and_keeps_the_hour(build) -> None:
    assert build.shifted("2018-07-04T16:42:10", 2558) == "2025-07-05T16:42:10"


def test_the_utc_instant_follows_the_offset_where_the_picture_was_taken(build) -> None:
    assert build.utc_instant("2025-07-15T17:26:00", "+03:00") == "2025-07-15T14:26:00.000Z"
    assert build.utc_instant("2025-07-01T01:30:00", "+02:00") == "2025-06-30T23:30:00.000Z"


def test_finland_runs_an_hour_ahead_of_the_rest_of_the_trip(build) -> None:
    assert build.offset_for("Finland", "+02:00") == "+03:00"
    assert build.offset_for("Norway", "+02:00") == "+02:00"
    assert build.offset_for(None, "+02:00") == "+02:00"


@pytest.mark.parametrize(
    ("title", "caption"),
    [
        ("File:Ålesund Aksla lub 2025-07-28 img02.jpg", "Ålesund Aksla"),
        ("File:Fähre Moskenes-Værøy lub 2025-07-23 img05.jpg", "ferry Moskenes-Værøy"),
        ("File:Balloons on a string (Unsplash).jpg", "Balloons on a string"),
    ],
)
def test_a_caption_is_the_title_without_its_bookkeeping(build, title, caption) -> None:
    assert build.caption_from_title(title) == caption


def test_share_alike_and_non_commercial_licences_are_refused(build) -> None:
    assert {"CC0", "CC BY 4.0"} <= build.ACCEPTED_LICENCES
    assert not {"CC BY-SA 4.0", "CC BY-NC 2.0", "CC BY-ND 4.0"} & build.ACCEPTED_LICENCES


def test_a_credit_row_names_the_file_author_source_licence_and_hash(build) -> None:
    record = {
        "file": "north-0712-0012.jpg",
        "sha256": "a" * 64,
        "source": {
            "title": "Møns Klint lub 2025-07-12 img10.jpg",
            "author": "Lukas Beck",
            "page": "https://commons.wikimedia.org/wiki/File:M%C3%B8ns_Klint.jpg",
            "licence": "CC BY 4.0",
        },
    }
    assert build.credit_row(record) == (
        "| `north-0712-0012.jpg` | Møns Klint lub 2025-07-12 img10.jpg | Lukas Beck "
        "| https://commons.wikimedia.org/wiki/File:M%C3%B8ns_Klint.jpg | CC BY 4.0 "
        f"| `{'a' * 64}` |"
    )


def test_a_face_box_past_the_edge_is_kept_inside_the_picture(build) -> None:
    """A close-up's detected box can start above the frame; Immich stores it inside."""
    face = build.pinned_face("Lou", (369.0, -14.6, 704.1, 878.1), width=1280, height=853)

    assert face == {"person": "Lou", "x": 0.2883, "y": 0.0, "w": 0.5501, "h": 1.0}
    assert 0 <= face["x"] <= face["x"] + face["w"] <= 1
