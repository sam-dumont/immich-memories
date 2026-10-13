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
    from collections.abc import Callable, Collection

    from immich_memories.config_loader import Config
    from immich_memories.timeperiod import DateRange
    from immich_memories.titles.film_stories import FilmStories

from immich_memories.i18n import elide_french, film_text, resolve_film_locale
from immich_memories.titles.title_source import TitleSource, override_source

logger = logging.getLogger(__name__)

__all__ = [
    "film_hemisphere",
    "holiday_title",
    "resolve_film_title",
    "template_title",
    "years_spanned",
]

# The people a special day's title may name, when the run named none: the most present.
_MOST_PEOPLE = 4


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


def _places_by_day(clips: list[Any]) -> list[str]:
    """Where the cut's pictures were taken, one line per day: "2025-07-05: Ixelles, Belgium"."""
    from immich_memories.analysis.place_names import shown_city

    by_day: dict[str, dict[str, None]] = {}
    for clip in clips:
        if (asset := getattr(clip, "asset", None)) is None:
            continue
        exif = getattr(asset, "exif_info", None)
        place = ", ".join(
            part
            for part in (shown_city(exif), getattr(exif, "country", None) if exif else None)
            if part
        )
        if place:
            day = asset.local_taken_at.date().isoformat()
            by_day.setdefault(day, {})[place] = None
    return [f"{day}: {' / '.join(places)}" for day, places in sorted(by_day.items())]


def _people_in_pictures(clips: list[Any]) -> list[str]:
    """The named people the cut's pictures show most, most present first."""
    from collections import Counter

    seen = Counter(
        person.name
        for clip in clips
        for person in (getattr(getattr(clip, "asset", None), "people", None) or [])
        if getattr(person, "name", "")
    )
    return [name for name, _count in seen.most_common(_MOST_PEOPLE)]


def film_hemisphere(
    config: Config, memory_type: str | None, preset_params: dict | None
) -> str | None:
    """The hemisphere that names this film's season: the one its window was built for.

    A season run carries the hemisphere its dates came from; anything else reads the
    home base. Without it a summer is titled by its months.
    """
    if memory_type == "season" and (hemisphere := (preset_params or {}).get("hemisphere")):
        return str(hemisphere)
    return config.trips.hemisphere


def _period_title(
    config: Config, memory_type: str | None, date_range: DateRange, preset_params: dict | None
) -> str | None:
    """A period film's title as the rules write it, which its model title must lead with."""
    from immich_memories.titles.title_routing import PERIOD_MEMORY_TYPES

    if (memory_type or "year") not in PERIOD_MEMORY_TYPES:
        return None
    return template_title(
        config, memory_type=memory_type, date_range=date_range, person_name=None,
        preset_params=preset_params,
    )[0]  # fmt: skip


def _place_and_kind_from_clips(clips: list[Any]) -> tuple[str, str] | None:
    """The place the film's own selected pictures name most often, and its kind.

    Reuses the special-day scan's own reading of EXIF rather than re-scanning
    anything: the film already has these clips in hand, and a day's place does
    not change between the scan that found it and the film that shows it.
    """
    from immich_memories.analysis.special_day_title import place_and_kind_from_assets

    assets = [asset for c in clips if (asset := getattr(c, "asset", None))]
    return place_and_kind_from_assets(assets)


def _day_in_place_title(place_name: str, kind: str, locale: str) -> str:
    """ "A day in {place}" with the right preposition, never a wrong one.

    Reuses the trip machinery (`place_phrases`): a language with a rule for
    this place's kind gets a proper phrase ("en France", "we Włoszech"); a
    language or a place with none (Polish/Russian/Japanese/Chinese/Korean do
    not cover every city and region, and some locales have no module at all)
    gets the neutral form with no preposition at all, place first -- the same
    rule the trip title follows (see `_trip_titles.generate_trip_title`).
    """
    from immich_memories.i18n import film_text
    from immich_memories.i18n_places import localise_country, localise_place
    from immich_memories.place_phrases import Place, place_phrase

    place = Place(place_name, kind)
    if phrase := place_phrase(locale, place):
        return film_text("title.day_in_place_with", locale, phrase=phrase)
    localised = (
        localise_country(place_name, locale)
        if kind == "country"
        else (localise_place(place_name, locale) or place_name)
    )
    return film_text("title.day_in_place_neutral", locale, place=localised)


def _ordinal_day(day: int, locale: str) -> str:
    """The day of the month as a date names it: French says "1er juillet",
    not "1 juillet", for the first of the month.

    A catalogue key of its own (`date.ordinal_1`), read through the same
    `film_text` machinery `i18n.get_ordinal` uses -- not `get_ordinal`
    itself, whose `ordinal.1` is bound to "année" (feminine, "1ère Année")
    and would be the wrong gender here.
    """
    from immich_memories.i18n import film_text

    if locale == "fr" and day == 1:
        return film_text("date.ordinal_1", locale)
    return str(day)


def _special_day_place_title(
    clips: list[Any], config: Config, date_range: DateRange
) -> tuple[str, str] | None:
    """(title, subtitle) naming a special day after its place, in the film's
    language, for when there is no model to reword the catalogue's title.

    The catalogue's own title is banked in English (#1959) and cannot be
    reworded without one; naming the day after where it was still beats an
    English headline or losing the occasion to the generic month-and-year
    card. The day's own date rides in the subtitle so the film never drops
    the year just because the title names the place instead of the calendar.
    """
    from immich_memories.i18n import month_name_forms

    if (found := _place_and_kind_from_clips(clips)) is None:
        return None
    place_name, kind = found
    locale = resolve_film_locale(config.title_screens.locale if config.title_screens else "en")
    day = date_range.start.date()
    month = month_name_forms(day.month, locale)["month_of"]
    subtitle = f"{_ordinal_day(day.day, locale)} {month} {day.year}"
    return _day_in_place_title(place_name, kind, locale), subtitle


def _special_day_fallback(
    memory_type: str | None, clips: list[Any], config: Config, date_range: DateRange
) -> tuple[str, str] | None:
    """A special day named after its place when nothing else names it.

    Catalogued or not: a day the scan never found is still one day somewhere, and the
    month-and-year card ("July 2025") says nothing about it.
    """
    if memory_type != "special_day":
        return None
    return _special_day_place_title(clips, config, date_range)


def _title_override_result(
    title_override: str,
    subtitle_override: str | None,
    *,
    memory_type: str | None,
    memory_preset_params: dict | None,
    locale: str,
) -> tuple[str, str | None, TitleSource] | None:
    """The (title, subtitle, source) to return for ``title_override``, or ``None``.

    ``None`` means this override is a special day's catalogue title (#1959):
    an English fact banked at scan time, not a ready title, so the caller
    clears it and falls through to the model and its template below instead
    of showing it verbatim -- unless the film's own language already IS
    English, in which case the catalogue's words are already right and
    rerouting them would only risk a model mangling them or a place fallback
    discarding a title the catalogue got to keep (#1985 review).
    """
    source = override_source(title_override, memory_type, memory_preset_params)
    if source is TitleSource.OCCASION and memory_type == "special_day" and locale != "en":
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
    stories: FilmStories | None,
) -> tuple[str | None, str | None, TitleSource | None]:
    """Ask the reader for a title; any failure falls back to the template layers."""
    from dataclasses import replace

    from immich_memories.titles.llm_titles import memory_title_facts

    display = (memory_preset_params or {}).get("person_display_names")
    if display is not None:
        person_names = [name for name in display.values() if name]
    if not person_names and memory_type == "special_day":
        person_names = _people_in_pictures(clips)
    facts = replace(
        memory_title_facts(memory_preset_params),
        stories=stories,
        period_title=_period_title(config, memory_type, date_range, memory_preset_params),
    )
    if facts.album_name is None and memory_type != "album":
        facts = replace(facts, album_name=_album_of_the_cut(album_lookup))

    start, end = date_range.start.date(), date_range.end.date()
    # Resolved here, not left to the prompt builder: "auto" must never reach
    # the model, which would otherwise read it literally as "Language: Auto".
    locale = resolve_film_locale(config.title_screens.locale if config.title_screens else "en")
    try:
        suggestion = ask(
            memory_type=memory_type or "year",
            locale=locale,
            start_date=str(start),
            end_date=str(end),
            duration_days=(end - start).days,
            daily_locations=_places_by_day(clips) or None,
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
    """Whether this run should put the question to the reader at all.

    Never for a holiday: its title is the holiday's own name and the years in the cut, and a
    model asked for one wrote a season label over years the film did not show.
    """
    if enabled is False or memory_type == "holiday":
        return False
    if not configured:
        if enabled:
            logger.warning("--llm-title needs a configured LLM; using the template title")
        return False
    if enabled:
        return True

    from immich_memories.titles.title_routing import OCCASION_MEMORY_TYPES, PEOPLE_MEMORY_TYPES

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
    stories: FilmStories | None = None,
    ask: Callable[..., Any] = _ask_the_llm,
) -> tuple[str | None, str | None, TitleSource | None]:
    """Return the (title, subtitle, source) the run should use.

    Owns the whole precedence so the caller gains no branches: an explicit
    title wins, then the model's, then the template (signalled by ``None``,
    with no source: the template layers name it later). The subtitle falls
    back to ``subtitle_override`` on every path. ``stories`` are the cut's own,
    read from its plan: what the model may name the film, or its subtitle, after.

    A special day's catalogue title travels through this same ``title_override``
    slot (see ``title_source.override_source``), but it is an English fact
    banked at scan time, not a ready title (#1959): it is cleared here rather
    than returned verbatim, so the model gets to reword it -- or, with no
    model, the film falls back to a template in its own language instead of
    an English headline.
    """
    locale = resolve_film_locale(config.title_screens.locale if config.title_screens else "en")

    if title_override:
        override_result = _title_override_result(
            title_override,
            subtitle_override,
            memory_type=memory_type,
            memory_preset_params=memory_preset_params,
            locale=locale,
        )
        if override_result is not None:
            return override_result
        if subtitle_override == (memory_preset_params or {}).get("subtitle"):
            subtitle_override = None

    llm_config = config.llm
    if not _asks_the_model(
        enabled=enabled,
        memory_type=memory_type,
        configured=bool(llm_config.enabled and llm_config.model),
    ):
        if fallback := _special_day_fallback(memory_type, clips, config, date_range):
            return fallback[0], fallback[1], TitleSource.FALLBACK
        return None, subtitle_override, None

    model_result = _model_suggested_title(
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
        stories=stories,
    )
    if model_result[0] is None and (
        fallback := _special_day_fallback(memory_type, clips, config, date_range)
    ):
        return fallback[0], fallback[1], TitleSource.FALLBACK
    return model_result


def holiday_title(
    preset_params: dict,
    memory_type: str | None,
    end: Any,
    locale: str,
    years: Collection[int] = (),
) -> tuple[str, None] | None:
    """A holiday film's title: the holiday's own name and the years the cut shows, or None.

    "Assomption · 2004–2026": the name in the film's language, then the span of the years
    with footage, the first to the last (owner ruling: a list of every run of years was too
    much). Never a season label, and never a year with no footage at either end, so the years
    come from the cut (`years`); before there is a cut, the name stands alone. No fallback occasion: a holiday that arrives without its parameter keeps the
    template's own title rather than claiming to be somebody's Christmas.
    """
    holiday = preset_params.get("holiday")
    if memory_type != "holiday" or not end or not holiday:
        return None
    from immich_memories.memory_types.factory import holiday_label

    name = holiday_label(
        holiday,
        end.year,
        locale,
        country=preset_params.get("country") or "US",
        own_name=preset_params.get("holiday_name"),
    )
    return (f"{name} · {years_spanned(years)}" if years else name), None


def years_spanned(years: Collection[int]) -> str:
    """Years as a title writes them: the first to the last ("2004–2026"), one year alone."""
    first, last = min(years), max(years)
    return str(first) if first == last else f"{first}\u2013{last}"


def birthday_title(
    preset_params: dict,
    memory_type: str | None,
    end: Any,
    person_name: str | None,
    locale: str,
) -> tuple[str, str | None] | None:
    """Name the birthday being celebrated, even when the search includes earlier birthdays.

    The year of the birthday over whose birthday it is ("2026", "Anniversaire de Kit"): a
    birthday film titled with the person's name alone never said what it celebrated.
    """
    if memory_type != "person_spotlight" or not preset_params.get("birthday") or end is None:
        return None
    if not person_name:
        return str(end.year), None
    return str(end.year), birthday_words(person_name, locale)


def birthday_words(person_name: str, locale: str) -> str:
    """ "Kit's birthday", "Anniversaire d'Anne", in the film's language."""
    named = film_text("story.birthday", locale, name=person_name)
    return elide_french(named) if locale == "fr" else named


def template_title(
    config: Config,
    *,
    memory_type: str | None,
    date_range: DateRange,
    person_name: str | None,
    preset_params: dict | None = None,
    years: Collection[int] = (),
) -> tuple[str, str | None]:
    """The title and subtitle the render's template layers write when nothing names the film.

    The same inputs the title screen reads, so a plan that stops before rendering can say
    what the film opens on instead of "from the template" (#2153). ``years`` are the years
    the cut shows, which a holiday's title names.
    """
    from immich_memories.filename_builder import build_title_person_name
    from immich_memories.generate_privacy import generate_trip_title_text
    from immich_memories.titles.text_builder import generate_title, infer_selection_type

    params = preset_params or {}
    locale = resolve_film_locale(config.title_screens.locale)
    if occasion := holiday_title(params, memory_type, date_range.end, locale, years):
        return occasion
    if memory_type == "trip" and (trip := generate_trip_title_text(params, locale)):
        return trip, None
    name = build_title_person_name(
        memory_type=memory_type,
        preset_params=params,
        person_name=person_name,
        use_first_name_only=config.title_screens.use_first_name_only,
    )
    if birthday := birthday_title(params, memory_type, date_range.end, name, locale):
        return birthday
    # Calendar days, not instants: a season is recognised by its first and last day.
    start, end = date_range.start.date(), date_range.end.date()
    selection = infer_selection_type(start_date=start, end_date=end, memory_type=memory_type)
    info = generate_title(
        selection,
        start_date=start,
        end_date=end,
        person_name=name,
        locale=locale,
        hemisphere=film_hemisphere(config, memory_type, params),
    )
    return info.main_title, info.subtitle or None
