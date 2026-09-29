"""The trace: the translation as the owner reads it, one line per decision.

Nobody reviews a translation before it runs, so the trace is how the owner sees what the model
and the rules made of the words: which words each part took, the rule or the question that
decided it, and the votes. It is printed before anything runs and saved with the run.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from immich_memories.free_text.handoff import Film
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import Reason
from immich_memories.free_text.pool import Translation
from immich_memories.free_text.reading import PARTS, Reading, words_of
from immich_memories.free_text.translate import Ask
from immich_memories.tracking import timing

_READ_RULE = "the model split your words 3 times; a word counts where 2 answers agree"
# Mirrored into the run's attempt directory, beside its timings.
TRACE_FILE = "free-text-trace.private.txt"
# The funnel steps that set the request's scope; the subject and company then narrow it.
_SCOPE_STEPS = frozenset({"library", "when", "who", "where", "place names", "printed text"})


def explain(ask: Ask, *, film: Film | None = None) -> str:
    """The trace: READING, WHO, WHEN, WHERE, WHAT, FACTS, POOL, VERDICT, then FILM when given."""
    lines = [f'"{ask.request}"']
    for head, said in trace_blocks(ask, film=film):
        lines += [f"{head if n == 0 else '':<8} {line}" for n, line in enumerate(said)]
    return "\n".join(lines)


def trace_blocks(ask: Ask, *, film: Film | None = None) -> list[tuple[str, list[str]]]:
    """The trace's parts in order, each head with its lines; a part with nothing to say is left out."""
    translation, pool = ask.translation, ask.pool
    path = " -> ".join(f"{step.name} {step.kept}" for step in pool.funnel)
    steps = [f"{step.name}: {step.reason.line()}" for step in pool.funnel]
    occasion = [f"one occasion? {pool.occasion.line()}"] if pool.occasion else []
    blocks = [
        ("READING", _reading(translation.reading)),
        ("WHO", _said(translation.who.reasons) or ["nothing said -> anyone"]),
        ("WHEN", _said(translation.when.reasons)),
        ("WHERE", _said(translation.where.reasons)),
        ("WHAT", _said(translation.subject.reasons)),
        ("FACTS", list(translation.facts.reasons)),
        ("POOL", [path, *steps, *occasion]),
        ("VERDICT", [f"{pool.verdict}: {pool.why}"]),
        ("FILM", [film.line()] if film else []),
    ]
    return [(head, said) for head, said in blocks if said]


def pool_counts(ask: Ask) -> dict[str, int]:
    """How many pictures the pool holds, and how many of them are photos and videos."""
    pictures = ask.pool.pictures
    videos = sum(picture.media_kind == "video" for picture in pictures)
    return {"pictures": len(pictures), "photos": len(pictures) - videos, "videos": videos}


def trace_record(ask: Ask, film: Film) -> dict[str, object]:
    """The trace as data for a watcher such as the web client: the parts, the pool, the verdict."""
    return {
        "request": ask.request,
        "blocks": [{"head": head, "lines": said} for head, said in trace_blocks(ask, film=film)],
        "pool": pool_counts(ask),
        "verdict": ask.pool.verdict,
        "why": ask.pool.why,
        "film": {"route": film.route, "line": film.line(), "outcome": film.reason.outcome},
    }


def _reading(reading: Reading) -> list[str]:
    agreed = _parts({part: getattr(reading, part) for part in PARTS}) or "nothing"
    answers = [
        f"answer {n}: {_parts(answer) or 'empty'}" if answer else f"answer {n}: cut off twice"
        for n, answer in enumerate(reading.answers, 1)
    ]
    return [f"{_READ_RULE} -> {agreed}", *answers]


def _parts(said: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{part}: {' | '.join(said[part])}" for part in PARTS if said.get(part))


def _said(reasons: Iterable[Reason]) -> list[str]:
    return [reason.line() for reason in reasons]


def save_with_run(
    ask: Ask,
    film: Film | None,
    trace: str,
    *,
    people: Mapping[str, LibraryPerson] | None = None,
    record: Mapping[str, object] | None = None,
) -> None:
    """Keep the trace with the run being observed, where the report builder reads it.

    Outside an observed run (a dry run) there is nothing to keep it with: it was printed.
    `record` is the translation as data (`trace_record`), kept whole for the report.
    The names of the `people` the request linked and the place names it quotes join the
    run's private terms, and the report's vocabulary gives each person their role.
    """
    collected = timing.active()
    if collected is None:
        return
    translation, pool = ask.translation, ask.pool
    known = people or {}
    linked = [known[person] for person in translation.who.anchors if person in known]
    people_roles = [(person.name, person.role or "") for person in linked]
    places = [value for _, value in translation.facts.places]
    scoped = [step.kept for step in pool.funnel if step.name in _SCOPE_STEPS]
    collected.diagnostics["free_text"] = {
        "request": ask.request,
        "trace": trace,
        "translation": dict(record or {}),
        "verdict": pool.verdict,
        "film": film.route if film else None,
        "spec": _spec(translation, [name for name, _ in people_roles]),
        "funnel": {"in_scope": scoped[-1] if scoped else 0, "pool": len(pool.pictures)},
        # What a picture marked wrong or a missing word is checked against; never reported.
        "marks_basis": _marks_basis(ask),
        "privacy": {
            "people": _roles_by_name(linked),
            "areas": places,
            "text": list(pool.printed),
        },
    }
    collected.diagnostics.setdefault("attempt_files", {})[TRACE_FILE] = trace
    collected.private_terms.update(name for name, _ in people_roles)
    collected.private_terms.update(places)
    collected.private_terms.update(pool.printed)
    # Immich ids of everyone the request linked: a report hashes them wherever they appear.
    collected.private_ids.update({*translation.who.anchors, *translation.who.present})
    # An age or "since he was born" is dated from the birth date, which the trace then prints.
    collected.private_terms.update(str(person.birth_date) for person in linked if person.birth_date)


def _marks_basis(ask: Ask) -> dict[str, object]:
    reading, last = ask.translation.reading, ask.pool.funnel[-1]
    return {
        "pool": [picture.asset_id for picture in ask.pool.pictures],
        "anchors": sorted(ask.pool.anchors),
        "admitted": {"stage": last.name, "reason": last.reason.line()},
        "read": sorted(
            {
                word
                for part in PARTS
                for phrase in getattr(reading, part)
                for word in words_of(phrase)
            }
        ),
    }


def _spec(translation: Translation, names: Sequence[str]) -> dict[str, object]:
    when = translation.when
    return {
        "people": [{"value": name} for name in names],
        "when": {"value": f"{when.start or 'any time'} to {when.end or 'open'}"},
        "where": {"value": translation.where.scope},
        "subject": [{"word": word} for word in translation.subject.main],
        "alongside": [{"word": word} for word in translation.subject.also],
        "words": [{"word": word} for word in translation.subject.words],
    }


def _roles_by_name(people: Sequence[LibraryPerson]) -> dict[str, str]:
    # A request names people by their first name ("Cy at the beach"): each part of a full name
    # gets the person's role too, the full name first so it is replaced whole.
    roles: dict[str, str] = {}
    for person in people:
        roles.setdefault(person.name, person.role or "")
    for person in people:
        for part in person.name.split():
            roles.setdefault(part, person.role or "")
    return roles


def carry_to_render(saved: Mapping[str, Any]) -> None:
    """Keep a saved cut's request with the run that renders it.

    Rendering a cut records a new run, and the film links to that one: without the request
    (and the private words that redact it) its report would not say what was asked. The
    render's own picks replace the cut's.
    """
    collected = timing.active()
    record = saved.get("free_text")
    if collected is None or not isinstance(record, Mapping):
        return
    carried = copy.deepcopy(dict(record))
    carried.pop("picks", None)
    carried.get("funnel", {}).pop("engine_picks", None)
    collected.diagnostics["free_text"] = carried
    collected.private_terms.update(saved.get("private_terms", []))
    collected.private_ids.update(saved.get("private_ids", []))


def save_picks(asset_ids: Iterable[str]) -> None:
    """Keep the engine's picks from the pool with the free-text run they were filmed for.

    A report of a bad result shows which pictures the engine chose; a run without a
    translated request keeps nothing.
    """
    collected = timing.active()
    record = collected.diagnostics.get("free_text") if collected else None
    if record is None:
        return
    picks = list(dict.fromkeys(asset_ids))
    record["picks"] = picks
    record["funnel"]["engine_picks"] = len(picks)
