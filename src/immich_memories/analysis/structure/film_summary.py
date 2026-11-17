"""What a film was about, said from the shots it shows, on every tier (#2488).

The summary is the film's `thesis`: the plan's `story.thesis`, which the film page, `runs
story`, the music mood, the title model and the Immich description read. The rules reader
writes none, so this module writes it once the cut is settled:

- with a model (Full), two small questions (#2594). The first asks the period's thesis from
  the cut (`polish.period_thesis`): its heaviest stories, what their episodes were read as, and
  who is on the most pictures. The second asks one sentence of what the film shows, from that
  thesis and one line code counts from the shots: the three largest groups of them, each with
  what its episode was read as, then what the shots show people doing. The film's scope is part
  of both prompts, so the judgment bank, which keys an answer by its prompt, never hands a
  person, season or year film a month's summary;
- with no model (Basic), or when an answer is unusable, one line made only of the names of
  the stories that matter, in the film's language. Nothing in it is invented.

Measured on 79 stored cuts with the small reader, against the one-question summary it
replaces: it named a person or a place in 50 (34), read generic in 12 (51), named the occasion
in 22 (14), and every answer parsed, from prompts under half the size.

All of it is opt-in while model-written text is experimental (`title_screens.llm_titles`,
#2594): off, which is the default, the film has no summary and nothing is asked.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from babel import Locale
from babel.lists import format_list

from immich_memories.analysis.judgments.strict_json import bounded_model_text, final_json_object
from immich_memories.analysis.polish.period_thesis import FilmShots, read_thesis, thesis_prompt
from immich_memories.analysis.stories.names import span_label, story_text
from immich_memories.analysis.stories.replies import WEIGHTS
from immich_memories.i18n import babel_locale, film_text, resolve_film_locale

logger = logging.getLogger(__name__)

SUMMARY_VERSION = "film-summary-v4"
SUMMARY_MAX_TOKENS = 400
# Read whole in a film page or an Immich description.
_MAX_WORDS = 70
_MAX_CHARS = 600
# Days at home this close are the next week of the same stretch of home life.
_HOME_WEEK_GAP_DAYS = 7
# The weights that make a story one the period was about, before any smaller one.
_LEADING = ("dominant", "major")
# The groups of shots the summary's counted line names, largest first.
_GROUPS = 3
# What the shots show people doing, as the activity heads read them, in words a summary can
# use. Posing and working say nothing about what happened, so they are left out.
_DOING = {
    "playing": "playing",
    "eating-drinking": "a meal",
    "celebration": "a celebration",
    "sport-active": "being active outdoors",
    "sightseeing": "sightseeing",
    "performing": "a performance",
    "animal-nature": "animals and nature",
}
_VENUES = {"water": "by the water"}
_HEAD = re.compile(r"\b(activity|venue)=([a-z-]+)")
_MOST_DOING = 3

_PROMPT = """What does this film show? {version}
THE FILM: {scope}.
{occasion}ITS SHOTS, counted: {line}
THE PERIOD: {thesis}

One sentence of at most 25 words, in {language}: who it was with and what they did, the
shots first. Only these facts; no ids.
JSON only: {{"summary":"..."}}"""


def plain_summary(stories: Sequence[Mapping[str, Any]], locale: str) -> str:
    """One line made only of the names of the stories that matter, in the order they happened.

    The stories weighed dominant or major lead; a period with none of those names its heaviest
    stories instead. A trip's legs are told once, by the trip's name. "Kit's birthday, then the
    road north", in the film's language.
    """
    names = _told_names(stories, locale)
    if not names:
        return ""
    line = names[0]
    for later in names[1:]:
        line = film_text("summary.then", locale, earlier=line, later=later)
    return line


def read_summary(
    judge,
    shots: FilmShots,
    *,
    thesis: str,
    scope: str,
    locale: str,
    occasion: str = "",
) -> str:
    """The model's one sentence of what the film shows, from the period's `thesis` and a line
    code counts from the film's own shots.

    ValueError when the answer is unusable: not one line of plain text, or too long.
    """
    line = shows_line(shots)
    prompt = _PROMPT.format(
        version=SUMMARY_VERSION,
        scope=scope,
        occasion=f"THE OCCASION: {occasion}.\n" if occasion else "",
        line=line or "(none read)",
        thesis=thesis,
        language=_language(locale),
    )
    raw = judge.ask(
        "film-summary",
        prompt,
        max_tokens=SUMMARY_MAX_TOKENS,
        json_object=True,
        json_fields=("summary",),
    )
    text = bounded_model_text((final_json_object(raw) or {}).get("summary"), max_chars=_MAX_CHARS)
    if text is None or len(text.split()) > _MAX_WORDS:
        raise ValueError("the model gave no usable film summary")
    return text


def shows_line(shots: FilmShots) -> str:
    """What the film shows, counted: its three largest groups of shots, each with what the
    episode holding most of them was read as, then what the shots show people doing.

    "5 of 12: Kit blows out the candles; 4 of 12: a swim in the lake; 3 other shots. Doing:
    a meal (4), playing (2)". Built in code: a count is something code says better than a model.
    """
    total = len(shots.carriers)
    parts, told = [], 0
    for clips, said in shots.groups(_GROUPS):
        if said:
            parts.append(f"{clips} of {total}: {said.rstrip('.')}")
            told += clips
    if total > told:
        parts.append(f"{total - told} other shots")
    line = "; ".join(parts)
    if doing := _doing(shots.carriers):
        line += ". Doing: " + ", ".join(doing)
    return line


def period_thesis(source, judge, shots: FilmShots) -> str:
    """The thesis of this cut's period, in the film's language (`polish.period_thesis`).

    ValueError when the answer holds none.
    """
    locale = resolve_film_locale(source.config.title_screens.locale)
    stories = _shown(shots.stories, shots.carriers)
    prompt = thesis_prompt(
        shots,
        scope=film_scope(source.case),
        occasion=_occasion(source.case, stories),
        language=_language(locale),
    )
    return read_thesis(judge, prompt)


def one_place_once(text: str, places: Sequence[str], locale: str) -> str:
    """`text` with every list of places naming each place once (#2535).

    Fed two stories that went to the same towns, the model listed them all in one run
    ("in Lyon, Annecy, Grenoble, Lyon, Annecy and Chambéry"). A run of the stories' own
    places, joined the way the language lists them, is said again with its repeats left
    out; a place named again in another sentence is left alone. The Immich description reads
    it, for the summaries cuts already hold.
    """
    names = sorted({p.strip() for p in places if p and p.strip()}, key=len, reverse=True)
    if len(names) < 2:
        return text
    place = "|".join(re.escape(name) for name in names)
    joiner = "|".join(re.escape(j) for j in _list_joiners(locale))
    run = re.compile(rf"(?<!\w)(?:{place})(?:(?:{joiner})(?:{place}))+(?!\w)")
    one = re.compile(rf"(?<!\w)(?:{place})(?!\w)")

    def once(found: re.Match[str]) -> str:
        listed = one.findall(found.group(0))
        unique = list(dict.fromkeys(listed))
        if len(unique) == len(listed):
            return found.group(0)
        return format_list(unique, locale=_list_locale(locale))

    return run.sub(once, text)


def _list_locale(locale: str) -> Locale:
    # British English, as the film text writes it: no comma before the last "and".
    return babel_locale("en_GB" if locale == "en" else locale)


def _list_joiners(locale: str) -> list[str]:
    """What stands between two items of a list in this language: ", ", " and ", ", and "."""
    marks = ("\x00", "\x01", "\x02")
    found = {", "}
    for count in (2, 3):
        written = format_list(list(marks[:count]), locale=_list_locale(locale))
        for left, right in zip(marks, marks[1:count], strict=False):
            found.add(written.split(left, 1)[1].split(right, 1)[0])
    # A model writing English may put the serial comma Babel's British list leaves out.
    found |= {", " + j.strip() + " " for j in list(found) if j.strip() and j.strip() != ","}
    return sorted(found - {""}, key=len, reverse=True)


def summarise_the_film(
    source,
    ports,
    selection,
    carriers: Sequence[Mapping[str, Any]],
    *,
    record: Callable[[str, Mapping[str, Any]], None],
) -> None:
    """Write the film's summary on its story, unless a model synthesis already wrote one.

    Only with `title_screens.llm_titles` on: off, the film has no summary.

    Read from the shots the finished cut holds and the episode readings the run read. With a
    model (`ports.thin`) the model writes it; with none, or when an answer is unusable, the
    story names make the line.
    """
    story = selection.story
    if not source.config.title_screens.llm_titles:
        # Model-written text is opt-in while it is experimental (#2594), and the story-name
        # line reads as a list of places and dates: off, the film has no summary at all.
        story.thesis = ""
        record("film-summary", {"version": SUMMARY_VERSION, "tier": "off", "summary": ""})
        return
    if story.thesis:
        return
    stories = _shown(story.stories, carriers)
    locale = resolve_film_locale(source.config.title_screens.locale)
    scope = film_scope(source.case)
    thesis = fallback = ""
    if ports.thin is not None:
        shots = FilmShots(
            carriers=carriers,
            stories=story.stories,
            readings=ports.thin.readings(),
            line_of=selection.lines.get,
        )
        try:
            thesis = period_thesis(source, ports.judge, shots)
            story.thesis = read_summary(
                ports.judge,
                shots,
                thesis=thesis,
                scope=scope,
                locale=locale,
                occasion=_occasion(source.case, stories),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            logger.warning("The film summary was not usable (%s); it names its stories", exc)
            fallback = str(exc)
    tier = "full" if story.thesis else "basic"
    if not story.thesis:
        story.thesis = plain_summary(stories, locale)
    # A later render in another language reads this and leaves the summary out (#2535).
    story.thesis_locale = locale
    record(
        "film-summary",
        {
            "version": SUMMARY_VERSION,
            "tier": tier,
            "scope": scope,
            "thesis": thesis,
            "summary": story.thesis,
            "stories": [str(s.get("key")) for s in stories],
        }
        | ({"fallback": fallback} if fallback else {}),
    )


def film_scope(case) -> str:
    """What film this is, in words: its kind, its dates and who it is about."""
    dates = ", ".join(f"{_day(r.start)} to {_day(r.end)}" for r in case.ranges)
    people = ", ".join(case.people or ())
    about = f" about {people}" if people else ""
    return f"a {case.product} film{about}, {dates}"


def _occasion(case, stories: Sequence[Mapping[str, Any]]) -> str:
    """The film's occasion as its summary leads with it: a holiday with the years its cut shows."""
    occasion = str(getattr(case, "occasion", "") or "")
    if not occasion or case.product != "holiday":
        return occasion
    from immich_memories.titles.film_title import years_spanned

    years = {int(str(day)[:4]) for story in stories for day in story.get("days") or ()}
    return f"{occasion}, {years_spanned(years)}" if years else occasion


def _day(when: Any) -> str:
    return str(when)[:10]


def _language(locale: str) -> str:
    found: Locale = babel_locale(locale)
    return str(found.english_name or "English")


def _shown(
    stories: Sequence[Mapping[str, Any]], carriers: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The stories the cut holds a shot of, in the order they happened; all of them when the
    shots name none (a draft whose carriers predate story keys)."""
    keys = {str(c.get("story_episode") or "") for c in carriers}
    shown = [s for s in stories if str(s.get("key")) in keys] or list(stories)
    return sorted(shown, key=_first_day)


def _first_day(story: Mapping[str, Any]) -> str:
    days = story.get("days") or ()
    return str(days[0]) if days else ""


def _trip_name(story: Mapping[str, Any]) -> str:
    trip = story.get("trip")
    return trip.strip() if isinstance(trip, str) else ""


def _told_names(stories: Sequence[Mapping[str, Any]], locale: str) -> list[str]:
    """The names a plain summary tells, chronological, a trip once for all its legs, and weeks
    at home one after another once, as the span they cover."""
    weights = {str(s.get("weight") or "") for s in stories}
    told = set(_LEADING) & weights
    if not told:
        heaviest = next((w for w in WEIGHTS if w in weights and w != "none"), None)
        told = {heaviest} if heaviest else set()
    names: list[str] = []
    for run in _in_runs([s for s in stories if str(s.get("weight") or "") in told]):
        name = _run_name(run, locale)
        if name and name not in names:
            names.append(name)
    return names


def _in_runs(stories: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """The stories in the order they happened, weeks at home one after another as one run."""
    runs: list[list[Mapping[str, Any]]] = []
    for story in sorted(stories, key=_first_day):
        if story.get("at_home") and runs and _follows_at_home(runs[-1][-1], story):
            runs[-1].append(story)
        else:
            runs.append([story])
    return runs


def _follows_at_home(earlier: Mapping[str, Any], later: Mapping[str, Any]) -> bool:
    """Whether `later` is days at home within a week of `earlier`'s: the next week of a month,
    never the same day of another year in a film over several."""
    if not earlier.get("at_home"):
        return False
    ends, starts = list(earlier.get("days") or ()), list(later.get("days") or ())
    if not ends or not starts:
        return False
    gap = date.fromisoformat(str(starts[0])[:10]) - date.fromisoformat(str(ends[-1])[:10])
    return gap <= timedelta(days=_HOME_WEEK_GAP_DAYS)


def _run_name(run: Sequence[Mapping[str, Any]], locale: str) -> str:
    """One story's name, or a run of weeks at home as one span ("Days at home, 2–13 September"):
    four "Days at home" in a row said nothing about a month."""
    if len(run) > 1:
        days = sorted(str(day) for story in run for day in story.get("days") or ())
        if days:
            return story_text("story.home_days", locale, span=span_label(days[0], days[-1], locale))
    story = run[0]
    return _trip_name(story) or str(story.get("title") or "").strip()


def _doing(carriers: Sequence[Mapping[str, Any]]) -> list[str]:
    """What the shots show people doing, most shots first: "a meal (4)"."""
    seen: Counter[str] = Counter()
    for carrier in carriers:
        for head, label in _HEAD.findall(str(carrier.get("line") or "")):
            if word := (_DOING if head == "activity" else _VENUES).get(label):
                seen[word] += 1
    return [f"{word} ({count})" for word, count in seen.most_common(_MOST_DOING)]
