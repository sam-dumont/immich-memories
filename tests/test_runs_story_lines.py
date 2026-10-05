"""`runs story` reads like a shot list: a date on every shot, a short story label and a
reason in words (#2156)."""

from __future__ import annotations

from immich_memories.analysis.editorial_story_carriers import carrier_why
from immich_memories.operations.storyboard import storyboard_from_plan, storyboard_lines

_TITLE = " / ".join(f"playing at Park {n}" for n in range(1, 7))


def _plan(why: str) -> dict:
    return {
        "story": {"episodes": [{"key": "S1", "title": _TITLE}]},
        "carriers": [
            {
                "asset_id": f"shot-{n}",
                "kind": "still",
                "seconds": 4.0,
                "taken": f"2024-06-08T1{n}:15:00+00:00",
                "story_episode": "S1",
                "why": f"{_TITLE}: {why}",
            }
            for n in range(3)
        ],
    }


def _lines(why: str = "capture group") -> list[str]:
    return [
        line for line in storyboard_lines(storyboard_from_plan(_plan(why), None)) if "s " in line
    ]


def test_every_shot_names_its_capture_day():
    assert all("2024-06-08" in line for line in _lines())


def test_a_story_of_many_places_is_named_by_its_first_two():
    line = _lines()[0]

    assert "playing at Park 1 / playing at Park 2 and 4 more" in line
    assert "Park 3" not in line


def test_the_no_model_reason_is_said_in_words():
    line = _lines()[0]

    assert "capture group" not in line
    assert "best frame of its moment" in line


def test_a_reason_read_off_an_annotation_line_drops_its_timestamp_field():
    line = _lines("2024-06-08 10:15+00:00 | at Park 1 | with a friend")[0]

    assert "+00:00" not in line
    assert "at Park 1, with a friend" in line


def test_a_long_reason_is_cut_between_words():
    content = "posing at the lakeside with " + "somebody recurring " * 10
    why = carrier_why("A day", content)

    reason = why.removeprefix("A day: ")
    assert reason.endswith("…")
    assert reason.removesuffix("…").split()[-1] in {"somebody", "recurring"}
    assert len(reason) <= 81
