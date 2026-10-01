"""Nearby nominations scale with their capture groups, not every unrelated picture."""

from collections import UserDict
from datetime import UTC, datetime, timedelta

from immich_memories.analysis.editorial_story_shortlist import (
    DepictedChoice,
    nearby_picture_alternatives,
)


class CountedUnits(UserDict):
    def __init__(self, data):
        super().__init__(data)
        self.reads = 0

    def __getitem__(self, key):
        self.reads += 1
        return super().__getitem__(key)


def capture_groups(count):
    choices, units = [], {}
    start = datetime(2030, 5, 1, tzinfo=UTC)
    for group in range(count):
        for offset in (0, 6):
            key = f"{group}-{offset}"
            taken = (start + timedelta(hours=group, seconds=offset)).isoformat()
            choices.append(DepictedChoice(key, "outing", taken, "Walking", key))
            units[key] = ("outing", {"asset_id": key, "moment": str(group), "taken": taken})
    return choices, CountedUnits(units)


def test_unrelated_capture_groups_do_not_multiply_nomination_work():
    choices, units = capture_groups(200)
    result = nearby_picture_alternatives(choices[::2], choices, units, starred=lambda _: False)
    assert result == choices[1::2]
    # This is the performance contract: doubling unrelated groups must not square
    # source lookups. The limit leaves room for several passes over every source.
    assert units.reads <= 8 * len(choices)


def scan_alternatives(primary_choices, choices, units, *, starred):
    """The pre-index scan, retained as an independent ordering oracle."""
    from immich_memories.analysis.editorial_story_shortlist import capture_space_available

    used, extras = {c.key for c in primary_choices}, []
    for primary in primary_choices:
        if starred(primary):
            continue
        occupied = [units[primary.primary][1]]
        candidates = [
            c
            for c in choices
            if c.key not in used and not capture_space_available(units[c.primary][1], occupied)
        ]
        if candidates:
            alternative = min(candidates, key=lambda c: (not starred(c), c.taken))
            used.add(alternative.key)
            extras.append(alternative)
    return extras


def test_index_preserves_boundaries_missing_times_favourites_and_stable_ties():
    import random

    rng = random.Random(1692)
    choices, units = capture_groups(40)
    for index, choice in enumerate(choices):
        unit = units[choice.primary][1]
        unit["moment"] = rng.choice([None, "a", "b", "c"])
        unit["taken"] = rng.choice(
            [
                None,
                "invalid",
                "2030-05-01T00:00:00+00:00",
                "2030-05-01T00:04:59+00:00",
                "2030-05-01T00:05:00+00:00",
                "2030-04-30T19:00:00-05:00",
            ]
        )
        choice.taken = str(index % 3)  # stable ties need input order, not a new sort key
    for _ in range(20):
        rng.shuffle(choices)
        primary = choices[::4]
        favourites = {c.key for c in choices if rng.randrange(7) == 0}

        def starred(c, favourites=favourites):
            return c.key in favourites

        assert nearby_picture_alternatives(primary, choices, units, starred=starred) == (
            scan_alternatives(primary, choices, units, starred=starred)
        )


def test_index_preserves_whole_planner_decisions_and_prompts(tmp_path, monkeypatch):
    from immich_memories.analysis import editorial_story_carriers
    from tests.editorial_story_fixtures import ControlledStoryJudge
    from tests.test_editorial_duration_planner_integration import run, semantic_plan
    from tests.test_editorial_story_nearby_choices import nearby_source

    old_judge, new_judge = ControlledStoryJudge(), ControlledStoryJudge()
    with monkeypatch.context() as old:
        old.setattr(editorial_story_carriers, "nearby_picture_alternatives", scan_alternatives)
        baseline = run(nearby_source(tmp_path / "baseline"), old_judge)
    indexed = run(nearby_source(tmp_path / "indexed"), new_judge)
    assert semantic_plan(indexed) == semantic_plan(baseline)
    assert [(c["stage"], c["prompt"]) for c in new_judge.calls] == [
        (c["stage"], c["prompt"]) for c in old_judge.calls
    ]


def test_story_audit_keeps_its_values_with_compact_serialization(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from immich_memories.analysis import editorial_structure_planner
    from tests.editorial_story_fixtures import ControlledStoryJudge
    from tests.test_editorial_duration_planner_integration import run
    from tests.test_editorial_story_nearby_choices import nearby_source

    def pretty(payload, **options):
        options.pop("separators", None)
        return json.dumps(payload, **{**options, "indent": 1})

    old_source = nearby_source(tmp_path / "pretty")
    with monkeypatch.context() as old:
        old.setattr(editorial_structure_planner, "json", SimpleNamespace(dumps=pretty))
        run(old_source, ControlledStoryJudge())
    new_source = nearby_source(tmp_path / "compact")
    run(new_source, ControlledStoryJudge())
    old_audit = next(old_source.artifact_dir.rglob("period-story.private.json")).read_bytes()
    new_audit = next(new_source.artifact_dir.rglob("period-story.private.json")).read_bytes()
    assert json.loads(new_audit) == json.loads(old_audit)
    assert len(new_audit) < len(old_audit)
