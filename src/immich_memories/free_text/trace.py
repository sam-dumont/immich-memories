"""The trace: the translation as the owner reads it, one line per decision.

Nobody reviews a translation before it runs, so the trace is how the owner sees what the model
and the rules made of the words: which words each part took, the rule or the question that
decided it, and the votes. It is printed before anything runs and saved with the run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from immich_memories.free_text.handoff import Film
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import Reason
from immich_memories.free_text.pool import Translation
from immich_memories.free_text.reading import PARTS, Reading
from immich_memories.free_text.translate import Ask
from immich_memories.tracking import timing

_READ_RULE = "the model split your words 3 times; a word counts where 2 answers agree"
# Mirrored into the run's attempt directory, beside its timings.
TRACE_FILE = "free-text-trace.private.txt"
# The funnel steps that set the request's scope; the subject and company then narrow it.
_SCOPE_STEPS = frozenset({"library", "when", "who", "where", "place names", "printed text"})


def explain(ask: Ask, *, film: Film | None = None) -> str:
    """The trace: READING, WHO, WHEN, WHERE, WHAT, FACTS, POOL, VERDICT, then FILM when given."""
    translation, pool = ask.translation, ask.pool
    lines = [f'"{ask.request}"', *_reading(translation.reading)]
    lines += _block("WHO", _said(translation.who.reasons) or ["nothing said -> anyone"])
    lines += _block("WHEN", _said(translation.when.reasons))
    lines += _block("WHERE", _said(translation.where.reasons))
    lines += _block("WHAT", _said(translation.subject.reasons))
    lines += _block("FACTS", list(translation.facts.reasons))
    path = " -> ".join(f"{step.name} {step.kept}" for step in pool.funnel)
    steps = [f"{step.name}: {step.reason.line()}" for step in pool.funnel]
    occasion = [f"one occasion? {pool.occasion.line()}"] if pool.occasion else []
    lines += _block("POOL", [path, *steps, *occasion])
    lines += _block("VERDICT", [f"{pool.verdict}: {pool.why}"])
    lines += _block("FILM", [film.line()] if film else [])
    return "\n".join(lines)


def _reading(reading: Reading) -> list[str]:
    agreed = _parts({part: getattr(reading, part) for part in PARTS}) or "nothing"
    answers = [
        f"answer {n}: {_parts(answer) or 'empty'}" if answer else f"answer {n}: cut off twice"
        for n, answer in enumerate(reading.answers, 1)
    ]
    return _block("READING", [f"{_READ_RULE} -> {agreed}", *answers])


def _parts(said: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{part}: {' | '.join(said[part])}" for part in PARTS if said.get(part))


def _said(reasons: Iterable[Reason]) -> list[str]:
    return [reason.line() for reason in reasons]


def _block(head: str, lines: Sequence[str]) -> list[str]:
    return [f"{head if n == 0 else '':<8} {line}" for n, line in enumerate(lines)]


def save_with_run(
    ask: Ask,
    film: Film | None,
    trace: str,
    *,
    people: Mapping[str, LibraryPerson] | None = None,
) -> None:
    """Keep the trace with the run being observed, where the report builder reads it.

    Outside an observed run (a dry run) there is nothing to keep it with: it was printed.
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
        "verdict": pool.verdict,
        "film": film.route if film else None,
        "spec": _spec(translation, [name for name, _ in people_roles]),
        "funnel": {"in_scope": scoped[-1] if scoped else 0, "pool": len(pool.pictures)},
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
    # An age or "since he was born" is dated from the birth date, which the trace then prints.
    collected.private_terms.update(str(person.birth_date) for person in linked if person.birth_date)


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
