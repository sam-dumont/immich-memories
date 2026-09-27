"""A cut that stops before rendering is still a run: it can be reviewed, revised and rendered."""

from __future__ import annotations

from datetime import date

from immich_memories.operations.run_index import attempt_dir_for_run, record_cut_run
from immich_memories.tracking import RunDatabase
from tests.web_api_fixtures import api_client, config_in


def test_a_cut_without_a_film_is_a_run_the_review_page_can_open(tmp_path):
    config = config_in(tmp_path)
    attempt = config.cache.cache_path / "editorial-runs" / "june" / "attempts" / "a1"
    attempt.mkdir(parents=True)

    run_id = record_cut_run(
        config,
        attempt,
        memory_type="monthly_highlights",
        memory_key="monthly_highlights:2024-06",
        date_range=(date(2024, 6, 1), date(2024, 6, 30)),
        people=("Ana",),
        clips_selected=12,
        target_duration_seconds=60,
    )

    run = RunDatabase(config.cache.database_path).get_run(run_id)
    assert run is not None and run.status == "completed" and run.output_path is None
    assert (run.memory_type, run.clips_selected, run.memory_people) == (
        "monthly_highlights",
        12,
        ("ana",),  # the run database keeps people normalized, as generate records them
    )
    assert attempt_dir_for_run(config.cache.cache_path, run_id) == attempt
    assert api_client(config).get(f"/api/v1/runs/{run_id}").json()["film"] is False
