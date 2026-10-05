"""The --no-render plan reads like the end of a rendered run: the title it opens on, the CHECK
line and the cut in order (#2153), and the folder it would land in named once (#2155)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from immich_memories.cli import _pipeline_runner
from immich_memories.config_loader import Config
from immich_memories.filename_builder import apply_recipe_hash
from immich_memories.processing.output_canvas import OutputCanvas
from immich_memories.processing.timeline_budget import TimelinePlan
from immich_memories.timeperiod import DateRange

JUNE = DateRange(datetime(2024, 6, 1), datetime(2024, 6, 30, 23, 59, 59))


def _attempt(tmp_path: Path, *, review: int = 0) -> Path:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    carriers = [
        {
            "asset_id": f"shot-{n}",
            "kind": "still",
            "seconds": 4.0,
            "taken": f"2024-06-{8 + n:02d}T10:15:00+00:00",
            "story_episode": "S1",
        }
        for n in range(3)
    ]
    plan = {"story": {"episodes": [{"key": "S1", "title": "A garden lunch"}]}, "carriers": carriers}
    (attempt / "plan.private.json").write_text(json.dumps(plan))
    if review:
        rows = [{"asset_id": f"shot-{n}", "exposure_probability": 0.3} for n in range(review)]
        (attempt / "review-before-sharing.private.json").write_text(json.dumps({"pictures": rows}))
    return attempt


def _plan_output(tmp_path, capsys, monkeypatch, *, title=None, review=0) -> str:
    # WHY: keeping the cut writes a run row to the store; the plan text is what is under test.
    monkeypatch.setattr(_pipeline_runner, "_keep_cut_as_run", lambda *_a, **_k: "run-1")
    attempt = _attempt(tmp_path, review=review)
    result = SimpleNamespace(
        selected_clips=[],
        clip_segments={},
        stats={"editorial_attempt_directory": str(attempt)},
    )
    _pipeline_runner._finish_without_rendering(
        pipeline_result=result,
        timeline_plan=TimelinePlan(
            target_duration=60.0,
            content_budget=50.0,
            title_budget=9.5,
            title_duration=3.5,
            ending_duration=4.0,
            divider_duration=2.0,
            max_dividers=0,
            transition_budget=4.0,
        ),
        assets=[],
        photo_assets=[],
        config=Config(),
        output_canvas=OutputCanvas(width=1920, height=1080, orientation="landscape"),
        output_path=apply_recipe_hash(Path("/films/june.mp4"), "3c9e1f0a"),
        memory_type="monthly_highlights",
        date_range=JUNE,
        should_upload=False,
        album_name=None,
        music=None,
        no_music=True,
        progress=MagicMock(),
        task=None,
        title=title,
        subtitle=None,
        cut_run={},
    )
    return capsys.readouterr().out


def test_the_plan_names_the_template_title_the_film_opens_on(tmp_path, capsys, monkeypatch):
    out = _plan_output(tmp_path, capsys, monkeypatch)

    assert "Title: June 2024" in out
    assert "from the template" not in out


def test_an_explicit_title_is_printed_as_given(tmp_path, capsys, monkeypatch):
    out = _plan_output(tmp_path, capsys, monkeypatch, title="Garden days")

    assert "Title: Garden days" in out


@pytest.mark.parametrize("review", [0, 2])
def test_the_plan_ends_with_the_check_line_and_the_cut(tmp_path, capsys, monkeypatch, review):
    out = _plan_output(tmp_path, capsys, monkeypatch, review=review)

    assert f"CHECK {review} picture" in out
    assert "the cut, in order (3 pictures" in out
    assert out.index("CHECK") < out.index("the cut, in order")
    assert "A garden lunch" in out


def test_the_planned_output_names_the_recipe_hash_once(tmp_path, capsys, monkeypatch):
    out = _plan_output(tmp_path, capsys, monkeypatch)

    line = next(line for line in out.splitlines() if line.startswith("Output (planned)"))
    assert line == "Output (planned): /films/june_3c9e1f0a_<run id>/june_3c9e1f0a.mp4"
