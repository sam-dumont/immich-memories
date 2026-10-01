"""Repeated editorial reads reuse prose without hiding refreshed annotations."""

from immich_memories.analysis.editorial_structure_lines import UnitLines


class CountedLine(str):
    parses = 0

    def splitlines(self, keepends=False):
        self.parses += 1
        return super().splitlines(keepends)


def test_repeated_editorial_questions_parse_unchanged_prose_once():
    text = CountedLine("2026-01-01 | a child with a kite | setting: outside | activity=playing")
    lines = UnitLines({"picture": text})
    unit = {"asset_id": "picture", "kind": "still", "favourite": False}
    for _ in range(20):
        assert lines.description(unit) == "a child with a kite"
        assert lines.shows_life(unit)
    assert text.parses == 1


def test_refreshed_or_removed_annotation_never_reuses_stale_description():
    old = CountedLine("2026-01-01 | a child with a kite | setting: outside")
    mapping = {"picture": old}
    lines = UnitLines(mapping)
    unit = {"asset_id": "picture", "kind": "still", "favourite": False}
    assert lines.shows_life(unit)
    new = CountedLine("2026-01-01 | an empty beach | exposure: daylight")
    mapping["picture"] = new
    assert lines.description(unit) == "an empty beach"
    assert not lines.shows_life(unit)
    assert new.parses == 1
    del mapping["picture"]
    assert lines.description(unit) == ""
    assert not lines.shows_life(unit)
    mapping["picture"] = old
    assert lines.description(unit) == "a child with a kite"
    assert old.parses == 2


def test_separate_readers_keep_their_own_evidence_and_unknown_tags():
    unit = {"asset_id": "picture"}
    first = UnitLines({"picture": "future-tag: an unknown observation | a child"})
    second = UnitLines({"picture": "2026-01-01 | a beach | setting: outside"})
    assert first.description(unit) == "future-tag: an unknown observation"
    assert second.description(unit) == "a beach"
    assert first.description(unit) == "future-tag: an unknown observation"


def test_reuse_preserves_complete_planner_decisions_and_prompts(tmp_path, monkeypatch):
    from immich_memories.analysis.annotation_line_fields import content_of
    from tests.editorial_story_fixtures import ControlledStoryJudge
    from tests.test_editorial_duration_planner_integration import run, semantic_plan
    from tests.test_editorial_story_nearby_choices import nearby_source

    def uncached_description(self, unit):
        parts = content_of(self.line(unit)).split(" | ")
        described = [p for p in parts if p and not p.startswith(("setting:", "exposure:"))]
        return described[0] if described else ""

    old_judge, new_judge = ControlledStoryJudge(), ControlledStoryJudge()
    # WHY: the former reader is the decision oracle; both planners use real fixture evidence.
    with monkeypatch.context() as old:
        old.setattr(UnitLines, "description", uncached_description)
        before = run(nearby_source(tmp_path / "before"), old_judge)
    after = run(nearby_source(tmp_path / "after"), new_judge)
    assert semantic_plan(before) == semantic_plan(after)
    assert [(c["stage"], c["prompt"]) for c in old_judge.calls] == [
        (c["stage"], c["prompt"]) for c in new_judge.calls
    ]
