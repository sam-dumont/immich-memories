"""The label a run's film carries is built from its own record, on every upload path (#2505)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations.film_labelling import (
    label_for_cut,
    label_for_run,
    memory_type_label,
)
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.operations.storyboard import PLAN_FILE
from immich_memories.processing.render_inputs import write_cut_titles
from immich_memories.tracking.models import RunMetadata

SUMMARY = "Kit's birthday, then Lou and Pat's visit, then The road north"
PLAN = {
    "story": {
        "thesis": SUMMARY,
        "episodes": [
            {"title": "Kit's birthday", "occasion": "birthday", "trip": None},
            {"title": "Days at home", "occasion": None, "trip": None},
            {"title": "Lou and Pat's visit", "occasion": "visit", "trip": None},
            {"title": "Oslo", "occasion": "leg", "trip": "The road north"},
            {"title": "Oslo to Tromso", "occasion": "leg", "trip": "The road north"},
        ],
    }
}


def _tagging() -> Config:
    """An install that opted into film tags (`upload.film_tags`)."""
    config = Config()
    config.upload.film_tags = True
    return config


EXPECTED_TAGS = (
    "immich-memories/type/Monthly highlights",
    "immich-memories/year/2025",
    "immich-memories/story/Kit's birthday",
    "immich-memories/story/Lou and Pat's visit",
    "immich-memories/story/The road north",
)


def _attempt(tmp_path, *, title="July 2025"):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / PLAN_FILE).write_text(json.dumps(PLAN))
    write_cut_titles(attempt, title=title, subtitle=None, source=None, preset_params={})
    return attempt


def test_memory_types_read_as_the_film_type_list_names_them():
    assert memory_type_label("monthly_highlights") == "Monthly highlights"
    assert memory_type_label("person_spotlight") == "Person spotlight"
    assert memory_type_label("trip") == "Trip"
    assert memory_type_label("album") == "Album"
    assert memory_type_label(None) is None


def test_a_cut_is_labelled_from_its_plan_and_title(tmp_path):
    label = label_for_cut(
        _tagging(),
        memory_type="monthly_highlights",
        date_start=date(2025, 7, 1),
        date_end=date(2025, 7, 31),
        attempt_dir=_attempt(tmp_path),
    )

    assert label is not None
    assert label.description == f"July 2025 · {SUMMARY}"
    assert label.tags == EXPECTED_TAGS


def test_film_tags_are_opt_in_and_the_description_is_not(tmp_path):
    label = label_for_cut(
        Config(),
        memory_type="monthly_highlights",
        date_start=date(2025, 7, 1),
        date_end=date(2025, 7, 31),
        attempt_dir=_attempt(tmp_path),
    )

    assert label is not None
    assert label.description == f"July 2025 · {SUMMARY}"
    assert label.tags == ()


def test_a_film_with_no_kept_title_is_described_by_the_title_it_opens_on(tmp_path):
    label = label_for_cut(
        Config(),
        memory_type="monthly_highlights",
        date_start=datetime(2025, 7, 1),
        date_end=datetime(2025, 7, 31),
        attempt_dir=_attempt(tmp_path, title=None),
    )

    assert label is not None
    assert label.description.startswith("July 2025 · ")


def test_a_birthday_film_is_described_by_its_whole_title_screen(tmp_path):
    # WHY: a birthday's template title is the year, its subtitle whose birthday; the
    # description said "2026 · ..." and never whose birthday it was.
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / PLAN_FILE).write_text(json.dumps(PLAN))
    write_cut_titles(attempt, title=None, subtitle=None, source=None, preset_params={})

    label = label_for_cut(
        Config(),
        memory_type="person_spotlight",
        date_start=date(2021, 7, 4),
        date_end=date(2026, 7, 5),
        attempt_dir=attempt,
        person_name="Kit",
        preset_params={"birthday": True, "person_names": ["Kit"]},
    )

    assert label is not None
    assert label.description == f"2026 · Kit's birthday · {SUMMARY}"


def test_a_kept_title_and_its_subtitle_both_describe_the_film(tmp_path):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / PLAN_FILE).write_text(json.dumps(PLAN))
    write_cut_titles(
        attempt, title="Nordkapp", subtitle="Twenty days north", source="model", preset_params={}
    )

    label = label_for_cut(
        Config(),
        memory_type="trip",
        date_start=date(2025, 7, 1),
        date_end=date(2025, 7, 20),
        attempt_dir=attempt,
    )

    assert label is not None
    assert label.description == f"Nordkapp · Twenty days north · {SUMMARY}"


def test_a_holiday_film_is_described_by_the_years_its_cut_shows(tmp_path):
    # WHY: the film opened on "Assomption · 2004–2026"; the description, rebuilt from the run's
    # window, said "1997–2026" and tagged all thirty years.
    plan = {
        "story": {
            "thesis": SUMMARY,
            "episodes": [
                {"title": "15 August 2004", "chosen": ["M1"], "days": ["2004-08-15"] * 2},
                {"title": "15 August 2010", "chosen": [], "days": ["2010-08-15"] * 2},
                {"title": "15 August 2026", "chosen": ["M2"], "days": ["2026-08-15"] * 2},
            ],
        }
    }
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / PLAN_FILE).write_text(json.dumps(plan))
    write_cut_titles(attempt, title=None, subtitle=None, source=None, preset_params={})

    label = label_for_cut(
        _tagging(),
        memory_type="holiday",
        date_start=date(1997, 8, 13),
        date_end=date(2026, 8, 17),
        attempt_dir=attempt,
        preset_params={"holiday": "Assumption Day", "country": "BE"},
    )

    assert label is not None
    assert label.description == f"Assumption Day · 2004–2026 · {SUMMARY}"
    assert [t for t in label.tags if "/year/" in t] == [
        "immich-memories/year/2004",
        "immich-memories/year/2026",
    ]


def test_a_cut_with_no_plan_still_gets_its_type_and_year(tmp_path):
    label = label_for_cut(
        _tagging(),
        memory_type="trip",
        date_start=date(2025, 7, 1),
        date_end=date(2025, 7, 3),
        attempt_dir=None,
        title="Nordkapp",
    )

    assert label is not None
    assert label.description == "Nordkapp"
    assert label.tags == ("immich-memories/type/Trip", "immich-memories/year/2025")


def test_a_label_that_cannot_be_built_never_stops_the_upload(tmp_path):
    # WHY: an unreadable date range stands in for any bug in the facts
    assert (
        label_for_cut(
            Config(),
            memory_type="trip",
            date_start="not a date",  # type: ignore[arg-type]
            date_end=date(2025, 7, 3),
            attempt_dir=None,
        )
        is None
    )


def test_a_retry_rebuilds_the_label_the_first_upload_sent(tmp_path):
    config = Config()
    store = open_store(config)
    attempt = _attempt(tmp_path)
    run = RunMetadata(
        run_id="20251001_000000_abcd",
        created_at=datetime(2025, 10, 1, tzinfo=UTC),
        memory_type="monthly_highlights",
        date_range_start=date(2025, 7, 1),
        date_range_end=date(2025, 7, 31),
    )
    record_run_attempt(run.run_id, attempt, tmp_path / "film.mp4", store=store)

    first = label_for_cut(
        config,
        memory_type=run.memory_type,
        date_start=run.date_range_start,
        date_end=run.date_range_end,
        attempt_dir=attempt,
        title="July 2025",
    )

    assert label_for_run(config, run, store=store) == first


def test_a_generate_run_is_labelled_from_its_parameters_and_never_fails_on_them(tmp_path):
    from types import SimpleNamespace

    from immich_memories.operations.film_labelling import label_for_params

    params = SimpleNamespace(
        config=Config(),
        memory_type="monthly_highlights",
        date_start=date(2025, 7, 1),
        date_end=date(2025, 7, 31),
        editorial_attempt_dir=_attempt(tmp_path),
        title=None,
        person_name=None,
        memory_preset_params={},
    )

    label = label_for_params(params)

    assert label is not None
    assert label.description == f"July 2025 · {SUMMARY}"
    assert label_for_params(SimpleNamespace()) is None
