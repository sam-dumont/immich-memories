"""A film's Immich label, built from a run's own record (#2505).

The CLI, the web upload and the automation retry all describe the film the same way: this is
the one place that gathers the facts (title, memory type, dates, and the plan's summary and
stories) and hands them to `film_label`. A retry rebuilds the label from the stored run, so it
reads what the first attempt would have read.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from immich_memories.api.film_label import FilmLabel, film_label
from immich_memories.operations.storyboard import PLAN_FILE

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.db import Store
    from immich_memories.tracking.models import RunMetadata

logger = logging.getLogger(__name__)


def memory_type_label(memory_type: str | None) -> str | None:
    """The memory type as the film-type list names it, in sentence case ("Monthly highlights")."""
    if not memory_type:
        return None
    from immich_memories.memory_types import list_memory_types

    for entry in list_memory_types():
        if entry["type"] == memory_type:
            return _sentence(entry["name"])
    return _sentence(memory_type.replace("_", " "))


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:].lower()


def _as_date(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _read_plan_story(attempt_dir: Path | None) -> Mapping[str, Any]:
    if attempt_dir is None:
        return {}
    try:
        plan = json.loads((Path(attempt_dir) / PLAN_FILE).read_text())
    except (OSError, ValueError):
        return {}
    story = plan.get("story") if isinstance(plan, Mapping) else None
    return story if isinstance(story, Mapping) else {}


def _title_of_the_cut(
    config: Config,
    *,
    title: str | None,
    attempt_dir: Path | None,
    memory_type: str | None,
    start: date | None,
    end: date | None,
    person_name: str | None,
    preset_params: Mapping[str, Any] | None,
) -> str | None:
    """The title the film opens on: the one given, the one the cut kept, else the template's."""
    from immich_memories.processing.render_inputs import read_cut_titles

    kept = read_cut_titles(attempt_dir) if attempt_dir is not None else None
    if title or (kept and kept.title):
        return title or (kept.title if kept else None)
    if start is None or end is None:
        return None
    from immich_memories.timeperiod import DateRange
    from immich_memories.titles.film_title import template_title

    params = dict(preset_params or (kept.preset_params if kept else {}))
    return template_title(
        config,
        memory_type=memory_type,
        date_range=DateRange(datetime.combine(start, time.min), datetime.combine(end, time.min)),
        person_name=person_name,
        preset_params=params,
        years=range(start.year, end.year + 1),
    )[0]


def label_for_cut(
    config: Config,
    *,
    memory_type: str | None,
    date_start: date | datetime | None,
    date_end: date | datetime | None,
    attempt_dir: Path | None,
    title: str | None = None,
    person_name: str | None = None,
    preset_params: Mapping[str, Any] | None = None,
) -> FilmLabel | None:
    """The label for one film, or None when it cannot be built: a label never stops an upload."""
    start, end = _as_date(date_start), _as_date(date_end)
    try:
        story = _read_plan_story(attempt_dir)
        label = film_label(
            title=_title_of_the_cut(
                config,
                title=title,
                attempt_dir=attempt_dir,
                memory_type=memory_type,
                start=start,
                end=end,
                person_name=person_name,
                preset_params=preset_params,
            ),
            summary=str(story.get("thesis") or ""),
            type_label=memory_type_label(memory_type),
            date_start=start,
            date_end=end,
            episodes=[e for e in story.get("episodes") or () if isinstance(e, Mapping)],
        )
        # The type, year and story tags are opt-in (`upload.film_tags`); the description is not.
        return label if config.upload.film_tags else replace(label, tags=())
    except Exception as exc:  # WHY: the film is finished; a label we cannot build must not fail it
        logger.warning("Uploading without a description and tags: %s", type(exc).__name__)
        return None


def label_for_params(params: Any) -> FilmLabel | None:
    """The label for the film a `generate` run just made, from its parameters."""
    try:
        return label_for_cut(
            params.config,
            memory_type=params.memory_type,
            date_start=params.date_start,
            date_end=params.date_end,
            attempt_dir=params.editorial_attempt_dir,
            title=params.title,
            person_name=params.person_name,
            preset_params=params.memory_preset_params,
        )
    except Exception as exc:  # WHY: a label we cannot build must not fail a finished film
        logger.warning("Uploading without a description and tags: %s", type(exc).__name__)
        return None


def label_for_run(config: Config, run: RunMetadata, *, store: Store) -> FilmLabel | None:
    """The label for a stored run, from its attempt folder: what a retry or a web upload sends."""
    from immich_memories.operations.run_index import attempt_dir_for_run

    try:
        attempt_dir = attempt_dir_for_run(run.run_id, store=store)
    except Exception:  # WHY: a store that cannot say still leaves a label from the run's dates
        attempt_dir = None
    return label_for_cut(
        config,
        memory_type=run.memory_type,
        date_start=run.date_range_start,
        date_end=run.date_range_end,
        attempt_dir=attempt_dir,
        person_name=run.person_name,
    )
