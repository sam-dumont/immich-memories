"""A story's pictures as carrier rows, built once per story however often a stage asks."""

from types import SimpleNamespace

import pytest

from immich_memories.analysis.selection import candidates
from immich_memories.analysis.selection.candidates import story_candidates


def _film(stories: int, pictures: int):
    episodes = [SimpleNamespace(key=f"e{s}", moments=(f"m{s}",)) for s in range(stories)]
    rows = [
        {"key": f"s{s}", "episodes": [f"e{s}"], "title": f"Story {s}", "weight": "major"}
        for s in range(stories)
    ]
    selection = SimpleNamespace(
        story=SimpleNamespace(episodes=episodes, stories=rows),
        episodes=[{"episode": f"s{s}"} for s in range(stories)],
        lines={},
    )
    pool = SimpleNamespace(
        moment_assets={f"m{s}": [f"a{s}-{p}" for p in range(pictures)] for s in range(stories)}
    )
    units = {
        f"f{s}": [
            {"asset_id": f"a{s}-{p}", "taken": "2024-06-04T10:00:00"} for p in range(pictures)
        ]
        for s in range(stories)
    }
    return selection, SimpleNamespace(anchor_label={}), pool, units


@pytest.fixture
def rows_built(monkeypatch):
    built: list[str] = []
    real = candidates.carrier_row

    def counting(unit, **kwargs):
        built.append(unit["asset_id"])
        return real(unit, **kwargs)

    # WHY: a spy around the real row builder; it counts the work, the rows stay real.
    monkeypatch.setattr(candidates, "carrier_row", counting)
    return built


def test_every_slot_asking_for_every_story_builds_each_row_once(rows_built):
    """The polish asked for every story the cut holds on every removal slot (#2712)."""
    candidates_of = story_candidates(*_film(stories=5, pictures=20))

    first = {f"s{s}": candidates_of(f"s{s}") for s in range(5)}
    for _slot in range(30):
        again = {f"s{s}": candidates_of(f"s{s}") for s in range(5)}

    assert len(rows_built) == 5 * 20
    assert again == first


def test_a_caller_editing_its_rows_does_not_edit_the_next_callers(rows_built):
    candidates_of = story_candidates(*_film(stories=1, pictures=2))

    mine = candidates_of("s0")
    mine[0]["notable_record"] = "changed"
    mine[0]["moment_alternatives"].append("a0-1")

    theirs = candidates_of("s0")
    assert "notable_record" not in theirs[0]
    assert theirs[0]["moment_alternatives"] == []
    assert [row["asset_id"] for row in theirs] == ["a0-0", "a0-1"]


def test_an_unknown_story_has_no_pictures(rows_built):
    assert story_candidates(*_film(stories=1, pictures=2))("missing") == []
    assert rows_built == []
