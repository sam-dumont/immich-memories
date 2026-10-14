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

from immich_memories.api.film_label import FilmLabel, film_label, years_shown
from immich_memories.operations.storyboard import PLAN_FILE

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.db import Store
    from immich_memories.tracking.models import RunMetadata

logger = logging.getLogger(__name__)


# The film-type names the web client shows (`web/src/lib/labels.ts`), whose translations every
# language's UI catalogue already carries.
_TYPE_NAMES = {
    "year_in_review": "Year in Review",
    "season": "Season",
    "person_spotlight": "Person Spotlight",
    "multi_person": "Multi-Person",
    "monthly_highlights": "Monthly Highlights",
    "on_this_day": "On This Day",
    "album": "Album",
    "trip": "Trip",
    "holiday": "Holiday",
    "special_day": "Special day",
}


def memory_type_label(memory_type: str | None, locale: str = "en") -> str | None:
    """The memory type as the film-type list names it, in the film's language.

    English is in sentence case ("Monthly highlights"); another language takes the name its
    UI catalogue gives the type ("Moments du mois"), as its translator wrote it.
    """
    if not memory_type:
        return None
    from immich_memories.i18n import get_translator
    from immich_memories.memory_types import list_memory_types

    name = _TYPE_NAMES.get(memory_type) or next(
        (e["name"] for e in list_memory_types() if e["type"] == memory_type),
        memory_type.replace("_", " "),
    )
    translated = get_translator(locale, "ui").gettext(name)
    return _sentence(name) if locale == "en" or translated == name else translated


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:].lower()


def _as_date(value: date | datetime | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _summary_in(story: Mapping[str, Any], locale: str) -> str:
    """The plan's summary when it is in the film's language, else none (#2535).

    A cut rendered again in another language, or one made before the summary recorded its
    language, would describe a French film in English: the description is then its title.
    Places a summary lists more than once are said once.
    """
    if story.get("thesis_locale") != locale:
        return ""
    from immich_memories.analysis.editorial_film_summary import one_place_once

    places = [
        p
        for e in story.get("episodes") or ()
        if isinstance(e, Mapping)
        for p in e.get("places") or ()
    ]
    return one_place_once(str(story.get("thesis") or ""), [str(p) for p in places], locale)


def _ordinary_case(
    title: str | None, memory_type: str | None, params: Mapping[str, Any], locale: str
) -> str | None:
    """The title with a trip's title-card capitals in ordinary case, as other films read."""
    if not title or memory_type != "trip":
        return title
    from immich_memories.generate_privacy import generate_trip_title_text

    shouted = generate_trip_title_text(dict(params), locale)
    if not shouted or shouted not in title:
        return title
    return title.replace(
        shouted, generate_trip_title_text(dict(params), locale, capitals=False) or shouted
    )


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
    years: list[int],
) -> str | None:
    """The title screen the film opens on: the title given, the one the cut kept with its
    subtitle, else the template's. A birthday's template title is only the year; its
    subtitle says whose birthday it is."""
    from immich_memories.processing.render_inputs import read_cut_titles

    kept = read_cut_titles(attempt_dir) if attempt_dir is not None else None
    if title:
        return title
    if kept and kept.title:
        return _screen(kept.title, kept.subtitle)
    if start is None or end is None:
        return None
    from immich_memories.timeperiod import DateRange
    from immich_memories.titles.film_title import template_title

    params = _preset_params(preset_params, kept)
    return _screen(
        *template_title(
            config,
            memory_type=memory_type,
            date_range=DateRange(
                datetime.combine(start, time.min), datetime.combine(end, time.min)
            ),
            person_name=person_name,
            preset_params=params,
            years=years,
        )
    )


def _preset_params(given: Mapping[str, Any] | None, kept: Any) -> dict[str, Any]:
    return dict(given or (kept.preset_params if kept else {}))


def _screen(title: str, subtitle: str | None) -> str:
    from immich_memories.api.film_label import DESCRIPTION_SEPARATOR

    return DESCRIPTION_SEPARATOR.join(part for part in (title, subtitle) if part)


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
    from immich_memories.i18n import resolve_film_locale
    from immich_memories.processing.render_inputs import read_cut_titles

    start, end = _as_date(date_start), _as_date(date_end)
    try:
        locale = resolve_film_locale(config.title_screens.locale)
        story = _read_plan_story(attempt_dir)
        episodes = [e for e in story.get("episodes") or () if isinstance(e, Mapping)]
        kept = read_cut_titles(attempt_dir) if attempt_dir is not None else None
        screen = _title_of_the_cut(
            config,
            title=title,
            attempt_dir=attempt_dir,
            memory_type=memory_type,
            start=start,
            end=end,
            person_name=person_name,
            preset_params=preset_params,
            # The years the cut shows, as the title screen read them: a holiday's span.
            years=years_shown(episodes, start, end),
        )
        label = film_label(
            title=_ordinary_case(screen, memory_type, _preset_params(preset_params, kept), locale),
            summary=_summary_in(story, locale),
            type_label=memory_type_label(memory_type, locale),
            date_start=start,
            date_end=end,
            episodes=episodes,
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
