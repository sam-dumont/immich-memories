"""Decide a film's title for any surface: an explicit title, the model's, or the template.

A memory about people or an occasion is named by the model as soon as a reader
is configured: the template opens a three-person film on a date span with three
full names stacked underneath, and the family record holds enough to write
"<child> and her grandparents" instead. Trips keep their own prompt and their
own opt-in, and `--no-llm-title` pins the template for the contact-sheet
matrix, where a run that starts inventing titles makes every run before and
after it incomparable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from immich_memories.config_loader import Config
    from immich_memories.timeperiod import DateRange

from immich_memories.titles.title_source import TitleSource, override_source

logger = logging.getLogger(__name__)

__all__ = ["resolve_film_title"]


def _descriptions(clips: list[Any]) -> list[str]:
    """What the analyzer said about each selected clip, for the prompt."""
    return [d for c in clips if (d := getattr(c, "llm_description", None))]


def _ask_the_llm(**kwargs: Any) -> Any:
    from immich_memories.titles.llm_titles import generate_title_with_llm

    return asyncio.run(generate_title_with_llm(**kwargs))


def _album_of_the_cut(lookup: Callable[[], str | None] | None) -> str | None:
    """The album the cut mostly sits in, when the run can ask Immich for it."""
    if lookup is None:
        return None
    try:
        return lookup()
    except Exception:  # WHY: a title fact must not fail the whole run
        logger.debug("Album lookup failed; the title goes without it", exc_info=True)
        return None


def _place_from_clips(clips: list[Any]) -> str:
    """The place the film's own selected pictures name most often.

    Reuses the special-day scan's own reading of EXIF rather than re-scanning
    anything: the film already has these clips in hand, and a day's place does
    not change between the scan that found it and the film that shows it.
    """
    from immich_memories.analysis.special_day_title import place_from_assets

    assets = [asset for c in clips if (asset := getattr(c, "asset", None))]
    return place_from_assets(assets)


def _special_day_place_title(clips: list[Any], config: Config) -> str | None:
    """ "A day in {place}", in the film's language, for a special day with no model.

    The catalogue's own title is banked in English (#1959) and cannot be
    reworded without one; naming the day after where it was still beats an
    English headline or the generic month-and-year card.
    """
    from immich_memories.i18n import film_text

    if not (place := _place_from_clips(clips)):
        return None
    locale = config.title_screens.locale if config.title_screens else "en"
    return film_text("title.day_in_place", locale, place=place)


def _title_override_result(
    title_override: str,
    subtitle_override: str | None,
    *,
    memory_type: str | None,
    memory_preset_params: dict | None,
) -> tuple[str, str | None, TitleSource] | None:
    """The (title, subtitle, source) to return for ``title_override``, or ``None``.

    ``None`` means this override is a special day's catalogue title (#1959):
    an English fact banked at scan time, not a ready title, so the caller
    clears it and falls through to the model and its template below instead
    of showing it verbatim.
    """
    source = override_source(title_override, memory_type, memory_preset_params)
    if source is TitleSource.OCCASION and memory_type == "special_day":
        return None
    return title_override, subtitle_override, source


def _model_suggested_title(
    *,
    ask: Callable[..., Any],
    memory_type: str | None,
    config: Config,
    llm_config: Any,
    date_range: DateRange,
    person_names: list[str],
    clips: list[Any],
    memory_preset_params: dict | None,
    album_lookup: Callable[[], str | None] | None,
    subtitle_override: str | None,
) -> tuple[str | None, str | None, TitleSource | None]:
    """Ask the reader for a title; any failure falls back to the template layers."""
    from dataclasses import replace

    from immich_memories.titles.llm_titles import memory_title_facts

    display = (memory_preset_params or {}).get("person_display_names")
    if display is not None:
        person_names = [name for name in display.values() if name]
    facts = memory_title_facts(memory_preset_params)
    if facts.album_name is None and memory_type != "album":
        facts = replace(facts, album_name=_album_of_the_cut(album_lookup))

    start, end = date_range.start.date(), date_range.end.date()
    try:
        suggestion = ask(
            memory_type=memory_type or "year",
            locale=config.title_screens.locale if config.title_screens else "en",
            start_date=str(start),
            end_date=str(end),
            duration_days=(end - start).days,
            person_names=person_names or None,
            clip_descriptions=_descriptions(clips) or None,
            facts=facts,
            llm_config=llm_config,
        )
    except Exception:  # WHY: an optional title must not fail the whole run
        logger.warning("LLM title generation failed; using the template title", exc_info=True)
        return None, subtitle_override, None

    if not suggestion or not getattr(suggestion, "title", None):
        return None, subtitle_override, None
    subtitle = getattr(suggestion, "subtitle", None) or subtitle_override
    return suggestion.title, subtitle, TitleSource.MODEL


def _asks_the_model(*, enabled: bool | None, memory_type: str | None, configured: bool) -> bool:
    """Whether this run should put the question to the reader at all."""
    if enabled is False:
        return False
    if not configured:
        if enabled:
            logger.warning("--llm-title needs a configured LLM; using the template title")
        return False
    if enabled:
        return True

    from immich_memories.titles.llm_titles import OCCASION_MEMORY_TYPES, PEOPLE_MEMORY_TYPES

    return memory_type in PEOPLE_MEMORY_TYPES or memory_type in OCCASION_MEMORY_TYPES


def resolve_film_title(
    *,
    enabled: bool | None,
    title_override: str | None,
    subtitle_override: str | None = None,
    clips: list[Any],
    config: Config,
    memory_type: str | None,
    date_range: DateRange,
    person_names: list[str],
    memory_preset_params: dict | None = None,
    album_lookup: Callable[[], str | None] | None = None,
    ask: Callable[..., Any] = _ask_the_llm,
) -> tuple[str | None, str | None, TitleSource | None]:
    """Return the (title, subtitle, source) the run should use.

    Owns the whole precedence so the caller gains no branches: an explicit
    title wins, then the model's, then the template (signalled by ``None``,
    with no source: the template layers name it later). The subtitle falls
    back to ``subtitle_override`` on every path.

    A special day's catalogue title travels through this same ``title_override``
    slot (see ``title_source.override_source``), but it is an English fact
    banked at scan time, not a ready title (#1959): it is cleared here rather
    than returned verbatim, so the model gets to reword it -- or, with no
    model, the film falls back to a template in its own language instead of
    an English headline.
    """
    from_catalogue = False
    if title_override:
        result = _title_override_result(
            title_override,
            subtitle_override,
            memory_type=memory_type,
            memory_preset_params=memory_preset_params,
        )
        if result is not None:
            return result
        from_catalogue = True
        if subtitle_override == (memory_preset_params or {}).get("subtitle"):
            subtitle_override = None

    llm_config = config.llm
    if not _asks_the_model(
        enabled=enabled,
        memory_type=memory_type,
        configured=bool(llm_config.enabled and llm_config.model),
    ):
        if from_catalogue and (place_title := _special_day_place_title(clips, config)):
            return place_title, None, TitleSource.FALLBACK
        return None, subtitle_override, None

    return _model_suggested_title(
        ask=ask,
        memory_type=memory_type,
        config=config,
        llm_config=llm_config,
        date_range=date_range,
        person_names=person_names,
        clips=clips,
        memory_preset_params=memory_preset_params,
        album_lookup=album_lookup,
        subtitle_override=subtitle_override,
    )
