"""`runs story` reads like a shot list: a date on every shot, a short story label and a
reason in words (#2156, #2487)."""

from __future__ import annotations

from immich_memories.operations.storyboard import storyboard_from_plan, storyboard_lines

_TITLE = " / ".join(f"playing at Park {n}" for n in range(1, 7))


_LINE = "2024-06-08 10:15+00:00 | at Lakeside, Somewhere | with Kit (son) | activity=posing"


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
                "why": why,
                "line": _LINE,
                "favourite": True,
            }
            for n in range(3)
        ],
    }


def _lines(why: str = f"{_TITLE}: capture group") -> list[str]:
    return [
        line for line in storyboard_lines(storyboard_from_plan(_plan(why), None)) if "s " in line
    ]


def test_every_shot_names_its_capture_day():
    assert all("2024-06-08" in line for line in _lines())


def test_a_story_of_many_places_is_named_by_its_first_two():
    line = _lines()[0]

    assert "playing at Park 1 / playing at Park 2 and 4 more" in line
    assert "Park 3" not in line


def test_a_plan_that_stored_the_reader_s_own_words_reads_the_shot_s_facts():
    line = _lines()[0]

    assert "capture group" not in line
    assert "best frame of its moment" not in line
    assert line.endswith("Kit at Lakeside · starred")


def test_a_plan_that_stored_a_raw_annotation_line_reads_the_shot_s_facts():
    line = _lines(f"{_TITLE}: {_LINE}")[0]

    assert "+00:00" not in line
    assert "activity=" not in line
    assert line.endswith("Kit at Lakeside · starred")


def test_a_reason_in_words_is_shown_as_the_editor_wrote_it():
    line = _lines("Kit on the jetty · the only one with a person")[0]

    assert line.endswith("Kit on the jetty · the only one with a person")
