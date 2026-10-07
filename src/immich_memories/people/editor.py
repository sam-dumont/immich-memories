"""The companion editor's model — the people registry as a page can show it.

The settings page renders these and writes them back; none of it knows about
the web server, which is what lets the confirm flow be tested on a real store rather
than through a browser. The rule the whole module exists to serve is the registry's
own: the user's answer is the answer, so nothing here ever discards a
`confirmed:` field it did not understand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from immich_memories.db import Store
from immich_memories.people.account_ids import entry_ids, ids_by_account
from immich_memories.people.companion import (
    add_confirmed_person,
    declined_aliases,
    load_document,
    people_entries,
    remove_confirmed_relationship,
    save_confirmed,
    save_confirmed_relationship,
)
from immich_memories.people.companion import bind_alias as _bind_alias
from immich_memories.people.companion import decline_alias as _decline_alias
from immich_memories.people.companion import unbind_alias as _unbind_alias
from immich_memories.people.relationships import DETECTED_KINDS, RELATIONSHIP_CHOICES
from immich_memories.people.signatures import Tier, pair_key

# What inference can suggest, and nothing more. A role the graph cannot propose
# is a role only the user can name, and the free-text field is where they do
# it — inventing a relationship vocabulary here would put words in their mouth.
ROLE_SUGGESTIONS = (
    "partner",
    "child",
    "parent",
    "sibling",
    "family",
    "friend",
    "acquaintance",
)

# Declaration order in the enum is closeness order, and the roster is drawn in
# it — inner circle first. Derived rather than retyped so the two cannot drift.
TIER_ORDER = tuple(tier.value for tier in Tier)

CONFIRMED = "confirmed"
REJECTED = "rejected"

DETECTED = "detected"
UNNAMED = "unnamed"
NAMED = "named"

_GONE = "someone no longer in the registry"

_LINK_PROMPTS = {
    "tight-dyad": "appears in a large share of their pictures, both ways",
    "twin": "same family name and birth date",
    "duplicate": "the same name on a second person record",
}

# The link kinds only Immich can fix. The page words each one itself, through the UI catalogue.
FLAGGED_KINDS = frozenset({"twin", "duplicate"})


@dataclass
class LinkView:
    """One edge, and what the user has said about it."""

    kind: str
    target_id: str
    target_name: str
    confidence: float
    via: str
    inferred: bool
    decision: str | None = None
    reverse_kind: str | None = None
    # detected: the scan noticed it and nobody answered; unnamed: confirmed in an older
    # release without ever saying what the pair is; rejected; named: a real relationship.
    status: str = NAMED

    @property
    def prompt(self) -> str:
        return _LINK_PROMPTS.get(self.kind, self.via)


@dataclass
class PersonView:
    """One person as the editor shows them: the reading, and the user's answer."""

    person_id: str
    name: str
    birth_date: str | None
    tier: str
    count: int
    counts_reliable: bool
    evidence: str
    links: list[LinkView] = field(default_factory=list)
    role: str | None = None
    notes: str | None = None
    # Every id this person answers to, by the account that reads it (`people bind`'s doing).
    # A one-account registry has only `primary`; there is no reader for other accounts' names.
    aliases: dict[str, list[str]] = field(default_factory=dict)
    # Other accounts' people somebody said are not this one, by account: never suggested again.
    declined: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class CurationFlag:
    """Something only Immich can fix, surfaced where the user is already looking.

    `names` and `person_ids` are in the same order, because the page turns them
    into one "open this person in Immich" link each and sending somebody to the
    wrong record is worse than not offering the link.
    """

    kind: str
    names: tuple[str, ...]
    person_ids: tuple[str, ...]


def load_people(store: Store) -> list[PersonView]:
    """The people registry as a roster, inner circle first and busiest first within.

    An empty registry reads as an empty roster: somebody opening the page before
    their first scan should be told to run one, not shown a stack trace.
    """
    document = load_document(store)
    entries = people_entries(document)
    names = _names_by_id(entries)
    answers = _pair_answers(entries)
    declined = declined_aliases(document)
    people = [_view(entry, names, answers, declined) for entry in entries]
    return sorted(people, key=lambda person: (_tier_rank(person.tier), -person.count))


def save_person(store: Store, person: PersonView) -> None:
    """Write one person's answers back, through the registry's own writer.

    Only decided links are written down. An edge nobody has answered yet is
    the graph's opinion, and the graph's opinions live under `inferred:`.
    """
    save_confirmed(
        store,
        person.person_id,
        {
            "role": _cleaned(person.role),
            "links": [_confirmed_link_block(link) for link in person.links if link.decision],
            "notes": _cleaned(person.notes),
        },
    )


def _confirmed_link_block(link: LinkView) -> dict[str, str]:
    block = {
        "kind": link.kind,
        "with": link.target_id,
        "decision": str(link.decision),
    }
    if link.reverse_kind:
        block["reverse"] = link.reverse_kind
    return block


def add_person(store: Store, name: str) -> str:
    """Add an off-camera or not-yet-tagged person from the settings page."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("A person needs a name")
    return add_confirmed_person(store, cleaned)


def add_relationship(store: Store, source_id: str, kind: str, target_id: str) -> None:
    """Save one human answer; the registry writer maintains its reciprocal."""
    valid = {choice.kind for choice in RELATIONSHIP_CHOICES}
    if kind not in valid:
        raise ValueError(f"Unknown relationship kind: {kind}")
    save_confirmed_relationship(store, source_id, kind, target_id)


def bind_person_alias(store: Store, person_id: str, account: str, alias_id: str) -> None:
    """Declare that `alias_id`, as `account` reads it, is this person — `people bind`'s API.

    Binding only adds an id; name, birth date and confirmations stay as they are. An id
    already bound to somebody else is refused. Binding the same id to the same account
    again is a no-op, same as the CLI command.
    """
    cleaned = alias_id.strip()
    if not cleaned:
        raise ValueError("An alias id cannot be empty")
    entry = next(
        (e for e in people_entries(load_document(store)) if person_id in entry_ids(e)), None
    )
    if entry is not None and cleaned in ids_by_account(entry).get(account, []):
        return
    _bind_alias(store, person_id, cleaned, account=account)


def unbind_person_alias(store: Store, person_id: str, account: str, alias_id: str) -> None:
    """Take another account's id off this person; the person, their answers and ids stay."""
    _unbind_alias(store, person_id, alias_id.strip(), account=account)


def decline_person_alias(store: Store, person_id: str, account: str, alias_id: str) -> None:
    """Answer "not the same person" for one other-account person, for good."""
    cleaned = alias_id.strip()
    if not cleaned:
        raise ValueError("An alias id cannot be empty")
    _decline_alias(store, person_id, account, cleaned)


def remove_relationship(store: Store, source_id: str, kind: str, target_id: str) -> None:
    """Remove one relationship created by the user and its reciprocal."""
    remove_confirmed_relationship(store, source_id, kind, target_id)


def curation_flags(people: list[PersonView]) -> list[CurationFlag]:
    """The pairs the user has to go and fix in Immich, one flag per pair.

    Links are stored from both ends, so the same twin pair arrives twice; the
    pair key is what collapses them into the one prompt a person should see.
    A pair somebody has rejected raises nothing — two people can share a
    surname and a birthday without being twins, or a name without being one
    person, and a flag that has been answered is nagging rather than curation.
    """
    names = {person.person_id: person.name for person in people}
    seen = _rejected_pairs(people)
    flags: list[CurationFlag] = []
    for person in people:
        for link in person.links:
            if link.kind not in FLAGGED_KINDS or link.target_id not in names:
                continue
            pair = pair_key(person.person_id, link.target_id)
            if pair in seen:
                continue
            seen.add(pair)
            flags.append(
                CurationFlag(
                    kind=link.kind,
                    names=(person.name, names[link.target_id]),
                    person_ids=(person.person_id, link.target_id),
                )
            )
    return flags


def keep_apart(store: Store, kind: str, person_id: str, other_id: str) -> None:
    """Answer a curation flag "no": these two are not one person, nor twins to merge.

    Recorded as the rejection `curation_flags` already honours, so the flag stops
    coming back. Raises ValueError when the registry holds no such flagged pair.
    """
    person = next((p for p in load_people(store) if p.person_id == person_id), None)
    link = next(
        (
            candidate
            for candidate in (person.links if person else [])
            if candidate.kind == kind and candidate.target_id == other_id
        ),
        None,
    )
    if person is None or link is None or kind not in FLAGGED_KINDS:
        raise ValueError("That pair is not flagged in the people registry.")
    link.decision = REJECTED
    save_person(store, person)


def _rejected_pairs(people: list[PersonView]) -> set[tuple[str, str]]:
    """Pairs somebody has already said no to — seeded into the seen set."""
    return {
        pair_key(person.person_id, link.target_id)
        for person in people
        for link in person.links
        if link.decision == REJECTED
    }


def _view(
    entry: dict[str, Any],
    names: dict[str, str],
    answers: dict[frozenset[str], set[str]],
    declined: dict[str, dict[str, list[str]]],
) -> PersonView:
    inferred = _mapping(entry.get("inferred"))
    confirmed = _mapping(entry.get(CONFIRMED))
    evidence = _mapping(inferred.get("evidence"))
    return PersonView(
        person_id=entry_ids(entry)[0],
        name=str(entry.get("name") or "?"),
        birth_date=_text(entry.get("birth_date")),
        tier=str(inferred.get("tier") or ""),
        count=int(evidence.get("count") or 0),
        counts_reliable=inferred.get("counts_reliable", True) is not False,
        evidence=_evidence_line(evidence),
        links=_links(entry_ids(entry)[0], inferred, confirmed, names, answers),
        role=_text(confirmed.get("role")),
        notes=_text(confirmed.get("notes")),
        aliases=ids_by_account(entry),
        declined=declined.get(entry_ids(entry)[0], {}),
    )


def _links(
    own_id: str,
    inferred: dict[str, Any],
    confirmed: dict[str, Any],
    names: dict[str, str],
    answers: dict[frozenset[str], set[str]],
) -> list[LinkView]:
    """Every edge this person has, whether the scan found it or the user wrote it.

    A link somebody typed into an import by hand has no inferred counterpart, and
    an editor that only rendered what the scan found would delete it the next
    time the user pressed a button on this person.

    One row per pair: once a pair has a real relationship, the detected link and any
    placeholder confirmed in an earlier release are the same fact said worse, and a
    pair somebody said no to on either side is not asked about again.
    """
    decisions = _decisions(confirmed)
    views: list[LinkView] = []
    for link in _mappings(inferred.get("links")):
        if not link.get("with"):
            continue
        view = _link_view(link, names, decisions)
        if _hidden(view, answers.get(frozenset((own_id, view.target_id)), set())):
            continue
        if view.decision is None and UNNAMED in answers.get(
            frozenset((own_id, view.target_id)), set()
        ):
            view.status = UNNAMED
        views.append(view)
    known = {(view.kind, view.target_id) for view in views}
    for link in _mappings(confirmed.get("links")):
        if not link.get("with") or (str(link.get("kind") or "link"), str(link["with"])) in known:
            continue
        view = _hand_written_link(link, names)
        if not _hidden(view, answers.get(frozenset((own_id, view.target_id)), set())):
            views.append(view)
    return views


def _hidden(view: LinkView, pair: set[str]) -> bool:
    """Whether the pair's answers make this row redundant."""
    if view.kind not in DETECTED_KINDS:
        return False
    if NAMED in pair:
        return True
    return view.decision is None and REJECTED in pair


def _pair_answers(entries: list[dict[str, Any]]) -> dict[frozenset[str], set[str]]:
    """What has been answered for each pair, from either person's confirmed links.

    Each pair maps to some of `named` (a real relationship), `unnamed` (a detected kind
    confirmed, no real kind yet) and `rejected`.
    """
    canonical = {pid: entry_ids(entry)[0] for entry in entries for pid in entry_ids(entry)}
    found: dict[frozenset[str], set[str]] = {}
    for entry in entries:
        own = entry_ids(entry)[0]
        for link in _mappings(_mapping(entry.get(CONFIRMED)).get("links")):
            other = canonical.get(str(link.get("with")))
            if other is None:
                continue
            decision = str(link.get("decision") or CONFIRMED)
            kind = str(link.get("kind") or "link")
            state = (
                REJECTED if decision == REJECTED else UNNAMED if kind in DETECTED_KINDS else NAMED
            )
            found.setdefault(frozenset((own, other)), set()).add(state)
    return found


def _link_view(
    raw: dict[str, Any], names: dict[str, str], decisions: dict[tuple[str, str], str]
) -> LinkView:
    target_id = str(raw["with"])
    kind = str(raw.get("kind") or "link")
    decision = decisions.get((kind, target_id))
    return LinkView(
        kind=kind,
        target_id=target_id,
        target_name=names.get(target_id, _GONE),
        confidence=float(raw.get("confidence") or 0.0),
        via=str(raw.get("via") or ""),
        inferred=True,
        decision=decision,
        reverse_kind=None,
        status=_status(kind, decision, inferred=True),
    )


def _status(kind: str, decision: str | None, *, inferred: bool) -> str:
    if decision == REJECTED:
        return REJECTED
    if kind not in DETECTED_KINDS:
        return NAMED
    return UNNAMED if decision == CONFIRMED else DETECTED if inferred else UNNAMED


def _hand_written_link(raw: dict[str, Any], names: dict[str, str]) -> LinkView:
    """An edge nobody inferred, because somebody wrote it into an import."""
    target_id = str(raw["with"])
    kind = str(raw.get("kind") or "link")
    decision = str(raw.get("decision") or CONFIRMED)
    return LinkView(
        kind=kind,
        target_id=target_id,
        target_name=names.get(target_id, _GONE),
        confidence=0.0,
        via="you",
        inferred=False,
        decision=decision,
        reverse_kind=_text(raw.get("reverse")),
        status=_status(kind, decision, inferred=False),
    )


def _decisions(confirmed: dict[str, Any]) -> dict[tuple[str, str], str]:
    """What the user said about each relationship kind and person pair.

    A link written by hand carries no `decision:` — the documented shape is
    just kind and target — and writing it down at all is the confirmation.
    """
    return {
        (str(link.get("kind") or "link"), str(link["with"])): str(link.get("decision") or CONFIRMED)
        for link in _mappings(confirmed.get("links"))
        if link.get("with")
    }


def _evidence_line(evidence: dict[str, Any]) -> str:
    count = evidence.get("count") or 0
    months = evidence.get("active_months") or 0
    since = evidence.get("onset") or evidence.get("first_month")
    line = f"{count} pictures across {months} {'month' if months == 1 else 'months'}"
    return f"{line}, here since {since}" if since else line


def _names_by_id(entries: list[dict[str, Any]]) -> dict[str, str]:
    return {
        person_id: str(entry.get("name") or "?")
        for entry in entries
        for person_id in entry_ids(entry)
    }


def _tier_rank(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)


def _cleaned(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    """A hand-edited list read as mappings, skipping whatever else is in there."""
    return [_mapping(item) for item in value] if isinstance(value, list) else []
