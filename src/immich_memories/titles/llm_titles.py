"""LLM-powered title generation for memory videos."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from immich_memories.analysis.llm_query import query_llm
from immich_memories.analysis.prose_shapes import MAP_MODES, TRIP_TYPES, title_shape
from immich_memories.people.context import PersonPromptContext, load_people_prompt_context
from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
from immich_memories.titles.title_guards import (
    eliding_french,
    refusing_a_wrong_year,
    refusing_contentless_title,
    refusing_invented_names,
    refusing_single_year_title,
    required_years,
    requiring_the_place,
    requiring_the_year,
    restore_fact_casing,
)
from immich_memories.titles.title_routing import (
    OCCASION_MEMORY_TYPES,
    PEOPLE_MEMORY_TYPES,
    is_trip,
)
from immich_memories.titles.title_suggestion import TitleSuggestion

if TYPE_CHECKING:
    from pathlib import Path

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.db import Store

logger = logging.getLogger(__name__)

_VALID_TRIP_TYPES: set[str] = set(TRIP_TYPES)
_VALID_MAP_MODES: set[str] = set(MAP_MODES)
_MAX_TITLE_LEN = 80
_MAX_SUBTITLE_LEN = 120

_LOCALE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
    "pt-BR": "Brazilian Portuguese",
    "pt-PT": "European Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-Hans": "Simplified Chinese",
    "ru": "Russian",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "nb": "Norwegian",
    "fi": "Finnish",
}


@dataclass(frozen=True)
class TitlePrompt:
    """The question put to the reader, and the facts its answer may name.

    ``facts`` is empty for a prompt that makes the reader no such promise, and
    an empty ``facts`` asks for nothing to be checked.
    """

    text: str
    facts: str = ""


@dataclass(frozen=True)
class MemoryTitleFacts:
    """What the run knows about a memory beyond its dates, places and names.

    Everything here is a recorded fact the title may use: the people condition
    the selection ran on, the name the catalogue or the album owner already
    gave the occasion, and where to read the family record. No story text: the
    readings promote names off banners and signs, and a title may not invent.
    """

    people_condition: str | None = None
    person_match: str = "and"
    occasion_name: str | None = None
    album_name: str | None = None
    holiday: str | None = None
    # The trip's place as trip naming chose it ("Crete, Greece"): the title must name it.
    place: str | None = None
    people_store: Store | None = None
    today: date | None = None


def parse_title_response(raw: str) -> TitleSuggestion | None:
    """Parse LLM JSON response into TitleSuggestion.

    Strips markdown code blocks, validates fields, sanitizes strings.
    Returns None on parse failure.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    # Strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Try direct parse first, then extract JSON from thinking model output
    data = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Thinking models (Qwen3.5) output reasoning before JSON —
        # extract the last JSON object from the response
        json_match = re.search(r'\{[^{}]*"title"[^{}]*\}', text)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except (json.JSONDecodeError, ValueError):
                pass
    if data is None:
        logger.warning("LLM title response has no valid JSON: %.100s", raw)
        return None

    if not isinstance(data, dict) or "title" not in data:
        logger.warning("LLM title response missing 'title' key")
        return None

    title = _sanitize(str(data["title"]), _MAX_TITLE_LEN)
    if not title:
        return None

    subtitle = _sanitize(str(data["subtitle"]), _MAX_SUBTITLE_LEN) if data.get("subtitle") else None
    trip_type = data.get("trip_type") if data.get("trip_type") in _VALID_TRIP_TYPES else None
    map_mode = data.get("map_mode") if data.get("map_mode") in _VALID_MAP_MODES else None

    return TitleSuggestion(
        title=title,
        subtitle=subtitle,
        trip_type=trip_type,
        map_mode=map_mode,
    )


def _sanitize(text: str, max_len: int) -> str:
    """Remove control characters and cap length."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text).strip()
    return cleaned[:max_len]


_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_TEMPLATES: dict[str, str] = {}


def _load_prompt_template(name: str = "title_generation.md") -> str:
    """Load prompt template from external file (cached after first load)."""
    if name not in _PROMPT_TEMPLATES:
        _PROMPT_TEMPLATES[name] = (_PROMPT_DIR / name).read_text(encoding="utf-8")
    return _PROMPT_TEMPLATES[name]


def _condition_text(preset: Mapping[str, Any]) -> str | None:
    """The people condition the selection ran on, as one reads it aloud."""
    raw = preset.get("person_expression")
    if not raw:
        return None
    from immich_memories.api.person_expression import PersonExpression

    try:
        expression = PersonExpression.from_dict(raw)
        display = preset.get("person_display_names")
        if display is not None:
            if any(not display.get(leaf) for leaf in expression.leaf_values):
                return None
            expression = expression.map_leaves(lambda leaf: display[leaf])
        return str(expression)
    except (TypeError, ValueError):
        logger.debug("Unreadable people condition; the names carry the film", exc_info=True)
        return None


def _occasion_name(preset: Mapping[str, Any]) -> str | None:
    """What the catalogue saw on this day, months before anybody asked for a film.

    A special day's own title, when the scan could write one, is the vetted
    name for what happened; its subtitle rides along the same way. Both are
    banked as English facts (the catalogue is shared and stays English) for
    this prompt to reword into the film's language -- never used as a ready
    title, which is how an English headline used to reach a French film.
    """
    title = str(preset.get("title") or "").strip()
    subtitle = str(preset.get("subtitle") or "").strip()
    what = str(preset.get("what") or "").strip()
    # The title is the vetted name; `what` is the plainer description banked
    # alongside it. Neither replaces the other -- a title with no description
    # behind it is as thin a fact as a description with no name.
    name = " -- ".join(dict.fromkeys(part for part in (title, what, subtitle) if part))
    kind = str(preset.get("kind") or "").strip()
    if not name:
        return None
    return f"{name} (kind: {kind})" if kind else name


def memory_title_facts(
    preset_params: Mapping[str, Any] | None = None,
    *,
    album_name: str | None = None,
) -> MemoryTitleFacts:
    """Read the facts a run already carries out of its preset parameters."""
    preset = preset_params or {}
    return MemoryTitleFacts(
        people_condition=_condition_text(preset),
        person_match=str(preset.get("person_match") or "and"),
        occasion_name=_occasion_name(preset),
        album_name=album_name or preset.get("album_name") or None,
        holiday=preset.get("holiday") or None,
        place=preset.get("location_name") or None,
    )


def _age(born: date, at: date) -> str:
    """How old somebody was, in the unit that still carries meaning at that age."""
    days = (at - born).days
    if days < 0:
        return "not born yet"
    if days < 60:
        return f"{days} days"
    months = (at.year - born.year) * 12 + at.month - born.month - (at.day < born.day)
    if months < 24:
        return f"{months} months"
    return f"{months // 12} years {months % 12} months"


def _birth_date(context: PersonPromptContext | None) -> date | None:
    if context is None or not context.birth_date:
        return None
    try:
        return date.fromisoformat(context.birth_date)
    except ValueError:
        return None


def _people_by_name(people_store: Store | None) -> dict[str, PersonPromptContext]:
    by_name: dict[str, PersonPromptContext] = {}
    ambiguous: set[str] = set()
    for context in load_people_prompt_context(people_store, include_derived=True).values():
        if context.name in by_name:
            ambiguous.add(context.name)
        by_name[context.name] = context
    return {name: context for name, context in by_name.items() if name not in ambiguous}


def _relation_to_maker(context: PersonPromptContext | None) -> str:
    """How this person relates to the film's maker, never printing the maker's name."""
    if context is None or context.relationship_source == "unconfirmed":
        return "no recorded family relation"
    if context.relationship_source == "owner":
        return "is the film's maker"
    relation = context.relationship.replace("library owner", "the film's maker")
    return f"relation to the film's maker: {relation} ({context.relationship_source})"


def _person_line(name: str, context: PersonPromptContext | None, start: date, end: date) -> str:
    relation = _relation_to_maker(context)
    born = _birth_date(context)
    if born is None:
        return f"- {name}: birth date unknown; {relation}"
    return (
        f"- {name}: born {born}; {_age(born, start)} old at the start, "
        f"{_age(born, end)} at the end; {relation}"
    )


def _pair_line(name: str, other: str, context: PersonPromptContext | None) -> str:
    kinds = sorted(
        {
            f"{item.kind.replace('-', ' ')} ({item.source})"
            for item in (context.relationships if context else ())
            if item.target_name == other
        }
    )
    return f"- {name} -> {other}: {'; '.join(kinds) or 'no recorded relation'}"


def people_title_facts(
    person_names: Sequence[str],
    start: date,
    end: date,
    *,
    people_store: Store | None = None,
) -> str:
    """One line per person, then the family record for every ordered pair.

    Structure carries this further than instruction does: the model is shown
    how many people are in the film and what the record says about each pair,
    "no recorded relation" included, instead of a role towards somebody who is
    not in the film at all.
    """
    by_name = _people_by_name(people_store)
    # WHY: a bare "1" still let a small model pluralise the relationship noun
    # ("ses petits-enfants" for one grandchild); spell out the count in words.
    count_note = "one person, singular" if len(person_names) == 1 else str(len(person_names))
    lines = [f"People in the film: {count_note}"]
    lines += [_person_line(name, by_name.get(name), start, end) for name in person_names]
    if len(person_names) > 1:
        lines.append("Family record, between the people in the film:")
        lines += [
            _pair_line(name, other, by_name.get(name))
            for name in person_names
            for other in person_names
            if other != name
        ]
    return "\n".join(lines)


def _first_birthday(born: date) -> date | None:
    try:
        return born.replace(year=born.year + 1)
    except ValueError:  # 29 February has no anniversary the following year
        return None


def _birth_notes(name: str, born: date | None, start: date, end: date) -> list[str]:
    if born is None:
        return []
    notes = [f"starts on {name}'s birth date"] if born == start else []
    first = _first_birthday(born)
    if first is not None and end in (first, first - timedelta(days=1)):
        notes.append(f"ends on {name}'s first birthday")
    return notes


def _month_end(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1)


def _calendar_notes(start: date, end: date) -> list[str]:
    if start.year == end.year and (start.month, start.day, end.month, end.day) == (1, 1, 12, 31):
        return [f"the calendar year {start.year}"]
    if (
        (start.year, start.month) == (end.year, end.month)
        and start.day == 1
        and end == _month_end(start)
    ):
        return ["the calendar month"]
    return []


def span_title_facts(
    start: date,
    end: date,
    person_names: Sequence[str] = (),
    *,
    people_store: Store | None = None,
    today: date | None = None,
) -> str:
    """The span, and what it IS: a birth date, a first year, today, a calendar period."""
    notes = [f"{start} to {end} ({(end - start).days} days)"]
    by_name = _people_by_name(people_store) if person_names else {}
    for name in person_names:
        notes += _birth_notes(name, _birth_date(by_name.get(name)), start, end)
    if end == (today or date.today()):
        notes.append("ends today (open-ended)")
    notes += _calendar_notes(start, end)
    return "; ".join(notes)


def _year_requirement_line(required: frozenset[int]) -> str:
    """The fact line naming exactly what `requiring_the_year` will check for.

    Prompt wording that restates this rule in its own words drifts from the
    guard that actually enforces it; every prompt instead defers to this one
    computed line.
    """
    if not required:
        return "Year(s) the title or subtitle must show: none"
    years = " and ".join(str(year) for year in sorted(required))
    return f"Year(s) the title or subtitle must show: {years}"


def _plain_condition(person_names: Sequence[str], match: str) -> str:
    """The condition a plain --person run selected on, written the way one reads it."""
    quoted = [json.dumps(name, ensure_ascii=False) for name in person_names]
    if not quoted:
        return "none recorded"
    if len(quoted) == 1:
        return quoted[0]
    return "(" + (" OR " if match == "or" else " AND ").join(quoted) + ")"


def _people_prompt(
    lang: str,
    memory_type: str,
    start: date,
    end: date,
    person_names: Sequence[str],
    facts: MemoryTitleFacts,
    year_line: str,
) -> TitlePrompt:
    condition = facts.people_condition or _plain_condition(person_names, facts.person_match)
    known = people_title_facts(person_names, start, end, people_store=facts.people_store)
    if facts.album_name:
        known += f"\nAlbum this film sits in: {facts.album_name}"
    span = span_title_facts(
        start, end, person_names, people_store=facts.people_store, today=facts.today
    )
    return TitlePrompt(
        _load_prompt_template("title_people.md")
        .replace("{lang}", lang)
        .replace("{memory_type}", memory_type)
        .replace("{condition}", condition)
        .replace("{people_facts}", known)
        .replace("{span}", span)
        .replace("{required_year}", year_line),
        f"{condition}\n{known}\n{span}",
    )


def _occasion_lines(
    facts: MemoryTitleFacts,
    start: date,
    end: date,
    daily_locations: Sequence[str] | None,
    person_names: Sequence[str],
) -> list[str]:
    lines: list[str] = []
    if facts.occasion_name:
        lines.append(f"The occasion, as catalogued: {facts.occasion_name}")
    if facts.album_name:
        lines.append(f"Album name in Immich: {facts.album_name}")
    if facts.holiday:
        lines.append(f"Holiday: {facts.holiday}")
    if daily_locations:
        lines.append("Places by day:")
        lines += [f"  {entry}" for entry in daily_locations[:30]]
    if person_names:
        lines.extend(
            (
                "People most present in the pictures, in order:",
                people_title_facts(person_names, start, end, people_store=facts.people_store),
            )
        )
    return lines


def _occasion_prompt(
    lang: str,
    memory_type: str,
    start: date,
    end: date,
    facts: MemoryTitleFacts,
    *,
    daily_locations: Sequence[str] | None,
    person_names: Sequence[str],
    year_line: str,
) -> TitlePrompt:
    span = span_title_facts(
        start, end, person_names, people_store=facts.people_store, today=facts.today
    )
    known = "\n".join(_occasion_lines(facts, start, end, daily_locations, person_names))
    return TitlePrompt(
        _load_prompt_template("title_occasion.md")
        .replace("{lang}", lang)
        .replace("{memory_type}", memory_type)
        .replace("{span}", span)
        .replace("{occasion_facts}", known)
        .replace("{required_year}", year_line),
        f"{span}\n{known}",
    )


def build_title_prompt(
    memory_type: str,
    locale: str,
    start_date: str,
    end_date: str,
    duration_days: int,
    *,
    daily_locations: list[str] | None = None,
    country: str | None = None,
    person_names: list[str] | None = None,
    clip_descriptions: list[str] | None = None,
    smart_objects: list[str] | None = None,
    facts: MemoryTitleFacts | None = None,
) -> TitlePrompt:
    """Build the prompt this memory is named from: people, occasion, or trip."""
    lang = _LOCALE_NAMES.get(locale, locale.capitalize())
    known = facts or MemoryTitleFacts()
    names = list(person_names or ())
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    year_line = _year_requirement_line(
        required_years(memory_type, start, end, tuple(names), known.holiday)
    )
    if memory_type in PEOPLE_MEMORY_TYPES:
        return _people_prompt(lang, memory_type, start, end, names, known, year_line)
    if memory_type in OCCASION_MEMORY_TYPES:
        return _occasion_prompt(
            lang,
            memory_type,
            start,
            end,
            known,
            daily_locations=daily_locations,
            person_names=names,
            year_line=year_line,
        )
    return _trip_prompt(
        lang=lang,
        memory_type=memory_type,
        start_date=start_date,
        end_date=end_date,
        duration_days=duration_days,
        daily_locations=daily_locations,
        country=country,
        person_names=person_names,
        clip_descriptions=clip_descriptions,
        smart_objects=smart_objects,
        album_name=known.album_name,
        place=known.place,
        year_line=year_line,
    )


def _trip_prompt(
    *,
    lang: str,
    memory_type: str,
    start_date: str,
    end_date: str,
    duration_days: int,
    daily_locations: list[str] | None = None,
    country: str | None = None,
    person_names: list[str] | None = None,
    clip_descriptions: list[str] | None = None,
    smart_objects: list[str] | None = None,
    album_name: str | None = None,
    place: str | None = None,
    year_line: str = "",
) -> TitlePrompt:
    context_lines: list[str] = [year_line] if year_line else []
    if place:
        context_lines.append(f"Place (name it, in the title's language): {place}")
    if album_name:
        context_lines.append(f"Album name in Immich: {album_name}")
    if daily_locations:
        context_lines.append("Daily locations (detect the travel pattern):")
        for loc in daily_locations[:30]:
            context_lines.append(f"  {loc}")
    if country:
        context_lines.append(f"Country: {country}")
    if person_names:
        context_lines.append(f"People: {', '.join(person_names)}")
    if clip_descriptions:
        context_lines.append(f"Clip content: {', '.join(clip_descriptions[:10])}")
    if smart_objects:
        context_lines.append(f"Objects: {', '.join(smart_objects[:20])}")

    return TitlePrompt(
        _load_prompt_template()
        .replace("{lang}", lang)
        .replace("{memory_type}", memory_type)
        .replace("{start_date}", start_date)
        .replace("{end_date}", end_date)
        .replace("{duration_days}", str(duration_days))
        .replace("{context_lines}", "\n".join(context_lines))
    )


def _guarded_suggestion(
    parsed: TitleSuggestion | None,
    *,
    prompt: TitlePrompt,
    memory_type: str,
    locale: str,
    start_date: str,
    end_date: str,
    person_names: tuple[str, ...],
    facts: MemoryTitleFacts | None,
) -> TitleSuggestion | None:
    """Run every title guard in turn, each free to trim or refuse what came before."""
    holiday = facts.holiday if facts else None
    people_store = facts.people_store if facts else None
    suggestion = eliding_french(parsed, locale)
    suggestion = refusing_invented_names(suggestion, prompt.facts)
    suggestion = refusing_unfounded_relationships(
        suggestion, person_names, locale, people_store, holiday
    )
    suggestion = refusing_a_wrong_year(suggestion, start_date, end_date)
    suggestion = requiring_the_year(
        suggestion, memory_type, start_date, end_date, person_names, holiday
    )
    suggestion = refusing_single_year_title(
        suggestion, memory_type, start_date, end_date, person_names, holiday
    )
    suggestion = refusing_contentless_title(
        suggestion, memory_type, start_date, end_date, person_names, locale
    )
    if memory_type in PEOPLE_MEMORY_TYPES or memory_type in OCCASION_MEMORY_TYPES:
        return suggestion
    return requiring_the_place(suggestion, facts.place if facts else None, locale)


async def generate_title_with_llm(
    memory_type: str,
    locale: str,
    start_date: str,
    end_date: str,
    duration_days: int,
    *,
    daily_locations: list[str] | None = None,
    country: str | None = None,
    person_names: list[str] | None = None,
    clip_descriptions: list[str] | None = None,
    smart_objects: list[str] | None = None,
    facts: MemoryTitleFacts | None = None,
    llm_config: LLMConfig | None = None,
    temperature: float = 0.1,
    judgments: Store | None = None,
) -> TitleSuggestion | None:
    """Generate a title using the LLM. Returns None on failure.

    With judgments, a title asked for twice about the same memory is paid for
    once: the prompt carries the dates, places, people, recorded relations and
    clip descriptions, so anything that would change the answer changes the key.
    """
    if llm_config is None:
        return None

    prompt = build_title_prompt(
        memory_type=memory_type,
        locale=locale,
        start_date=start_date,
        end_date=end_date,
        duration_days=duration_days,
        daily_locations=daily_locations,
        country=country,
        person_names=person_names,
        clip_descriptions=clip_descriptions,
        smart_objects=smart_objects,
        facts=facts,
    )

    try:
        raw = await query_llm(
            prompt.text,
            llm_config,
            temperature=temperature,
            max_tokens=8000,
            timeout_seconds=300,
            thinking=True,
            judgments=judgments,
            response_format=title_shape(trip=is_trip(memory_type)),
        )
        parsed = parse_title_response(raw)
        if parsed is not None:
            parsed = restore_fact_casing(parsed, prompt.facts or prompt.text)
        return _guarded_suggestion(
            parsed,
            prompt=prompt,
            memory_type=memory_type,
            locale=locale,
            start_date=start_date,
            end_date=end_date,
            person_names=tuple(person_names or ()),
            facts=facts,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        logger.warning("LLM title generation failed: %s", e, exc_info=True)
        return None
