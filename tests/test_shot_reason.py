"""Every shot in a cut says why it is there, in words a person would write (#2487).

The reason is built from the shot's own facts: who is on it, what its caption says (or where it
was taken when there is none), and what made it beat the rest of its moment. Never telemetry,
detector labels, timestamps or the reader's own vocabulary.
"""

from __future__ import annotations

import re

import pytest

from immich_memories.analysis.shot_reason import (
    REASON_CHARS,
    reads_as_telemetry,
    shot_reason,
    shot_reason_of_row,
)

_KIT = (
    "2025-07-05 14:51+00:00 | at Ixelles, Brussels Capital, Belgium | with Kit (son; 3 years old)"
)
_HEADS = "activity=posing, children=yes, location=indoor, people=one | resolution:1280x852"
_FRAMING = "subject-framing:3 (0.24% of the frame, inside the frame, the largest face)"


def _line(*parts: str) -> str:
    return " | ".join(("2025-07-05 14:51+00:00", *parts))


def test_names_who_is_on_it_and_where_without_any_telemetry():
    reason = shot_reason(f"{_KIT} | {_FRAMING} | {_HEADS}")

    assert reason == "Kit at Ixelles"


def test_names_without_notes_are_read_too():
    reason = shot_reason(_line("with Charlie; Kit; Robin", _HEADS))

    assert reason.startswith("Charlie, Kit and Robin")


def test_a_crowd_is_named_by_its_first_two():
    reason = shot_reason(_line("with Ann (friend); Bo (friend); Cy; Di (aunt; 40 years old)"))

    assert reason == "Ann, Bo and 2 others"


def test_the_caption_says_what_it_shows():
    line = _line("A girl in a party dress on the stairs.", "at Ixelles, Brussels, Belgium")

    assert shot_reason(line, story_title="Kit's birthday") == (
        "a girl in a party dress on the stairs, Ixelles"
    )


def test_the_place_is_left_out_when_the_story_already_carries_it():
    line = _line("A fountain in a square", "at Reine, Nordland, Norway")

    assert shot_reason(line, kind="video", story_title="Reine") == "a fountain in a square · video"


def test_a_story_named_after_everywhere_it_went_names_no_place_in_particular():
    title = " / ".join(f"Town {n}" for n in range(12)) + " / Reine"

    assert shot_reason(_line("at Reine, Nordland, Norway"), story_title=title) == "Reine"


def test_coordinates_are_not_a_place():
    assert shot_reason(_line("at 70.740,25.666", _HEADS)) == "a photo"


def test_a_star_says_so():
    assert shot_reason(f"{_KIT} | STARRED by the photographer", starred=True) == (
        "Kit at Ixelles · starred"
    )


def test_a_picture_the_owner_kept_says_so():
    assert shot_reason(_KIT, kept_by_owner=True) == "Kit at Ixelles · kept by the owner"


@pytest.mark.parametrize(
    ("media", "kind", "said"),
    [
        ("VIDEO 5s raw", "video", "video"),
        ("LIVE PHOTO, renders as a 3s clip", "live-motion", "Live Photo"),
        ("LIVE PHOTO BURST of 4 stills, stitches to a 3s clip", "live-motion", "Live Photo burst"),
    ],
)
def test_motion_says_what_kind_it_is(media, kind, said):
    reason = shot_reason(_line(media, "at Ixelles, Brussels, Belgium", _HEADS), kind=kind)

    assert reason == f"Ixelles · {said}"
    assert "5s raw" not in reason


def test_a_video_with_nothing_else_known_is_called_a_video():
    assert shot_reason(_line("VIDEO 5s raw", _HEADS), kind="video") == "a video"


def test_the_only_frame_with_a_person_says_so():
    siblings = [_line("at Ixelles, Brussels, Belgium", _HEADS)] * 2

    reason = shot_reason(_KIT, siblings=siblings)

    assert reason == "Kit at Ixelles · the only one with a person"


def test_the_only_frame_with_both_says_so():
    line = _line("with Pat (partner); Lou (daughter; 5 years old)")
    siblings = [_line("with Pat (partner)"), _line("with Lou (daughter; 5 years old)")]

    assert shot_reason(line, siblings=siblings) == "Pat and Lou · the only one with both"


def test_the_clearest_view_of_its_people_says_so():
    line = f"{_KIT} | {_FRAMING}"
    sibling = f"{_KIT} | subject-framing:1 (0.10% of the frame, at the frame's edge, ...)"

    assert shot_reason(line, siblings=[sibling]) == "Kit at Ixelles · the clearest view of Kit"


def test_the_sharpest_of_a_run_says_so():
    siblings = [f"{_KIT} | SOFT (blurry)", f"{_KIT} | SOFT (blurry)"]

    assert shot_reason(_KIT, siblings=siblings) == "Kit at Ixelles · the sharpest of 3"


def test_at_most_two_reasons_it_won():
    reason = shot_reason(
        f"{_KIT} | VIDEO 5s raw", kind="video", starred=True, siblings=[_line("at Ixelles")]
    )

    assert reason == "Kit at Ixelles · starred · video"


def test_a_long_caption_is_cut_between_words_and_the_reason_stays_short():
    caption = "A family of four on a couch watching a cartoon " + "in the evening light " * 6
    reason = shot_reason(_line(caption, "with Kit (son)"), starred=True)

    assert len(reason) <= REASON_CHARS
    assert reason.endswith("· starred")
    assert "… · starred" in reason


def test_nothing_known_still_reads_as_words():
    assert shot_reason("") == "a photo"


@pytest.mark.parametrize(
    "line",
    [
        f"{_KIT} | {_FRAMING} | {_HEADS}",
        _line("VIDEO 5s raw", "activity=sport-active, location=outdoor | resolution:1278x720"),
        _line("at Jette, Brussels Capital, Belgium", "children=yes, location=outdoor"),
        _line("FLAGGED nsfw (swimwear)", "DARK", "exposure:1/50", "duration:5.000s"),
        "Material picture p1: 2025-07-05 14:51+00:00 | with Kit (son) | resolution:500x333",
    ],
)
def test_no_reason_carries_telemetry(line):
    reason = shot_reason(line, kind="video" if "VIDEO" in line else "still")

    assert not reads_as_telemetry(reason), reason
    assert not re.search(r"\d{4}-\d\d-\d\d|%|=|resolution|framing|posing|sport-active", reason)


@pytest.mark.parametrize(
    "text",
    [
        "capture group",
        "2025-07-07 14:13+00:00 | at Jette",
        "with Kit | subject-framing:2 (2.01% of the frame",
        "at Jette, children=yes, location=outdoor",
        "VIDEO 5s raw",
        "resolution:1280x960",
    ],
)
def test_the_old_reasons_read_as_telemetry(text):
    assert reads_as_telemetry(text)


def test_a_carrier_row_is_read_for_its_facts():
    row = {
        "kind": "live-motion",
        "favourite": True,
        "line": _line(
            "LIVE PHOTO, renders as a 3s clip", "with Kit (son)", "STARRED by the photographer"
        ),
    }

    assert shot_reason_of_row(row) == "Kit · starred · Live Photo"


def test_a_row_the_owner_required_says_so():
    row = {"kind": "still", "line": _KIT, "owner_required": True}

    assert shot_reason_of_row(row) == "Kit at Ixelles · kept by the owner"
