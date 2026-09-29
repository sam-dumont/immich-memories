"""The people registry: the graph's findings, kept where a person can argue with them.

The registry lives in the store (#871). A scan fills every person's `inferred:` block and
the owner fills `confirmed:`. The contract that makes it safe to regenerate: **confirmed
beats inferred**. A refresh recomputes every `inferred:` block and copies every
`confirmed:` block through untouched, and a person somebody has annotated is never dropped,
even when they fall off the roster.

Callers speak the document `people.yaml` always had; `people.registry_store` maps it to rows
and `people.transfer` turns it into a YAML export and back.
"""

from __future__ import annotations

import copy
import functools
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from immich_memories.config_models import ACCOUNT_NAME_RULE, PRIMARY_ACCOUNT, is_account_name
from immich_memories.db import Store, open_store
from immich_memories.people.account_ids import (
    PERSON_ID,
    entry_ids,
    ids_by_account,
    place_ids,
    primary_ids,
)
from immich_memories.people.registry_store import lock_registry, read_document, write_document
from immich_memories.people.relationships import owner_role, reciprocal_kind

if TYPE_CHECKING:
    from immich_memories.people.graph import PeopleGraph, PersonNode
    from immich_memories.people.signatures import Link

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_P = ParamSpec("_P")
_R = TypeVar("_R")


def load_document(store: Store | None = None) -> dict[str, Any]:
    """The registry as a document, or an empty one before the first scan."""
    with (store or open_store()).connect() as connection:
        return read_document(connection)


def people_entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The person entries in a document, skipping anything malformed.

    An entry has to carry its ids (a list, or a list per account) to be an entry at all.
    The store only holds valid
    entries, but a document handed over from elsewhere (an import) may not.
    """
    people = document.get("people")
    if not isinstance(people, list):
        return []
    return [
        entry
        for entry in people
        if isinstance(entry, dict) and isinstance(entry.get("ids"), list | dict)
    ]


def retained_immich_ids(document: dict[str, Any]) -> set[str]:
    """Primary-account face ids a user deliberately kept, even below the scan floor."""
    retained: set[str] = set()
    for entry in people_entries(document):
        if not (_has_content(entry.get("confirmed")) or entry.get("origin") == "immich"):
            continue
        retained.update(
            person_id for person_id in primary_ids(entry) if not person_id.startswith("manual:")
        )
    return retained


def _one_writer(
    change: Callable[Concatenate[dict[str, Any], _P], _R],
) -> Callable[Concatenate[Store, _P], _R]:
    """Read, change and write the registry in one transaction, holding its lock throughout.

    A scan from the CLI and a confirmation from the web UI both rewrite the registry from
    what they read; without the lock, the later write drops the earlier one's change.
    """

    @functools.wraps(change)
    def locked(store: Store, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with store.begin() as connection:
            lock_registry(connection)
            document = read_document(connection)
            before = copy.deepcopy(document)
            result = change(document, *args, **kwargs)
            if document != before:
                write_document(connection, document)
        return result

    return locked


@_one_writer
def save_graph(document: dict[str, Any], graph: PeopleGraph) -> None:
    """Write the graph, preserving every confirmed field already in the registry."""
    kept = _confirmed_by_id(document)
    bound = _bound_aliases(document, {node.evidence.person_id for node in graph.people})
    # A node that is somebody's bound alias is that person already, not a second entry.
    aliased = {
        alias for seen, entry in bound.items() for alias in entry_ids(entry) if alias != seen
    }
    entries = [
        _entry_for(node, kept, bound.get(node.evidence.person_id))
        for node in graph.people
        if node.evidence.person_id not in aliased
    ]
    entries.extend(_annotated_strangers(document, graph))
    document.clear()
    document.update(
        {
            "version": SCHEMA_VERSION,
            "generated": (graph.built_at or datetime.now()).isoformat(timespec="seconds"),
            "owner": _owner_block(graph),
            "people": entries,
        }
    )


@_one_writer
def save_confirmed(document: dict[str, Any], person_id: str, confirmed: dict[str, Any]) -> None:
    """Replace one person's confirmed block, leaving everybody else alone."""
    entries = [entry for entry in people_entries(document) if person_id in entry_ids(entry)]
    if not entries:
        logger.warning("Nothing in the people registry to confirm for that person")
        return
    for entry in entries:
        entry["confirmed"] = copy.deepcopy(confirmed)


@_one_writer
def add_confirmed_person(
    document: dict[str, Any],
    name: str,
    *,
    person_id: str | None = None,
    role: str | None = None,
) -> str:
    """Add somebody the quantitative roster did not retain.

    A real Immich id may be supplied for a below-threshold face. Somebody who
    has no Immich face record gets a local id and remains a first-class graph
    node; being off camera is not evidence that a relative does not exist.
    An id the registry already holds answers with that person's id.
    """
    entries = people_entries(document)
    matches = [entry for entry in entries if entry.get("name") == name]
    if len(matches) > 1:
        msg = f"More than one person is named {name!r}; use a person id"
        raise ValueError(msg)
    if matches:
        return entry_ids(matches[0])[0]
    holder = next((entry for entry in entries if person_id in entry_ids(entry)), None)
    if holder is not None:
        return entry_ids(holder)[0]

    local_id = person_id or f"manual:{uuid.uuid4()}"
    document.setdefault("people", []).append(
        {
            "ids": [local_id],
            "name": name,
            "birth_date": None,
            "inferred": {
                "tier": None,
                "counts_reliable": False,
                "evidence": {},
                "links": [],
            },
            "confirmed": {"role": role, "links": [], "notes": None},
            "origin": "immich" if person_id else "manual",
        }
    )
    return local_id


@_one_writer
def save_confirmed_relationship(
    document: dict[str, Any], source_id: str, kind: str, target_id: str
) -> None:
    """Write one user relationship and its reciprocal as one transaction."""
    if source_id == target_id:
        raise ValueError("A person cannot have a relationship with themselves")
    source = _entry_with_id(document, source_id)
    target = _entry_with_id(document, target_id)
    reverse = reciprocal_kind(kind)
    _upsert_confirmed_link(source, kind, target_id, reverse)
    _upsert_confirmed_link(target, reverse, source_id, kind)
    _fill_owner_role(document, source, kind, target_id)
    _fill_owner_role(document, target, reverse, source_id)


@_one_writer
def remove_confirmed_relationship(
    document: dict[str, Any], source_id: str, kind: str, target_id: str
) -> None:
    """Remove one confirmed relationship and the reciprocal written with it."""
    source = _entry_with_id(document, source_id)
    target = _entry_with_id(document, target_id)
    source_link = _confirmed_link(source, kind, target_id)
    reverse = (
        str(source_link.get("reverse"))
        if source_link and source_link.get("reverse")
        else reciprocal_kind(kind)
    )
    _remove_confirmed_link(source, kind, target_id)
    _remove_confirmed_link(target, reverse, source_id)


@_one_writer
def bind_alias(
    document: dict[str, Any], person_id: str, alias_id: str, *, account: str | None = None
) -> None:
    """Confirm that `alias_id`, as `account` reads it, is the person `person_id` names.

    `account` None or `primary` is the primary account; any other name has to be one the
    config could hold, configured yet or not. The binding only adds an id: the person's name,
    birth date and confirmations stay exactly as they were, whatever the other account
    calls them. An id that already belongs to somebody else is an error, never a merge;
    binding the same id to the same person again changes nothing.
    """
    name = account or PRIMARY_ACCOUNT
    if name != PRIMARY_ACCOUNT and not is_account_name(name):
        msg = f"account {name!r} must be {PRIMARY_ACCOUNT!r} or {ACCOUNT_NAME_RULE}"
        raise ValueError(msg)
    person = _entry_with_id(document, person_id)
    holder = next(
        (entry for entry in people_entries(document) if alias_id in entry_ids(entry)), None
    )
    if holder is not None and holder is not person:
        msg = f"{alias_id!r} already belongs to {holder.get('name') or entry_ids(holder)[0]!r}"
        raise ValueError(msg)
    groups = ids_by_account(person)
    if holder is person:
        if alias_id not in groups.get(name, []):
            msg = f"{alias_id!r} is already bound to this person for another account"
            raise ValueError(msg)
        return
    own = entry_ids(person)[0]
    groups.setdefault(name, []).append(alias_id)
    place_ids(person, groups, own)


def _entry_with_id(document: dict[str, Any], person_id: str) -> dict[str, Any]:
    matches = [entry for entry in people_entries(document) if person_id in entry_ids(entry)]
    if len(matches) != 1:
        msg = f"Expected one people entry for {person_id!r}, found {len(matches)}"
        raise ValueError(msg)
    return matches[0]


def _confirmed_block(entry: dict[str, Any]) -> dict[str, Any]:
    confirmed = entry.get("confirmed")
    if not isinstance(confirmed, dict):
        confirmed = _blank_confirmed()
        entry["confirmed"] = confirmed
    confirmed.setdefault("role", None)
    confirmed.setdefault("links", [])
    confirmed.setdefault("notes", None)
    return confirmed


def _confirmed_link(entry: dict[str, Any], kind: str, target_id: str) -> dict[str, Any] | None:
    links = _confirmed_block(entry).get("links")
    if not isinstance(links, list):
        return None
    return next(
        (
            link
            for link in links
            if isinstance(link, dict) and link.get("kind") == kind and link.get("with") == target_id
        ),
        None,
    )


def _upsert_confirmed_link(
    entry: dict[str, Any], kind: str, target_id: str, reverse_kind: str
) -> None:
    confirmed = _confirmed_block(entry)
    links = confirmed["links"]
    if not isinstance(links, list):
        links = []
        confirmed["links"] = links
    existing = _confirmed_link(entry, kind, target_id)
    if existing is not None:
        existing["decision"] = "confirmed"
        existing["reverse"] = reverse_kind
        return
    links.append(
        {
            "kind": kind,
            "with": target_id,
            "reverse": reverse_kind,
            "decision": "confirmed",
        }
    )


def _remove_confirmed_link(entry: dict[str, Any], kind: str, target_id: str) -> None:
    confirmed = _confirmed_block(entry)
    links = confirmed.get("links")
    if not isinstance(links, list):
        return
    confirmed["links"] = [
        link
        for link in links
        if not (
            isinstance(link, dict) and link.get("kind") == kind and link.get("with") == target_id
        )
    ]


def _fill_owner_role(
    document: dict[str, Any], entry: dict[str, Any], kind: str, target_id: str
) -> None:
    owner = document.get("owner")
    owner_id = owner.get("person_id") if isinstance(owner, dict) else None
    confirmed = _confirmed_block(entry)
    if owner_id == target_id and not confirmed.get("role"):
        confirmed["role"] = owner_role(kind)


def _owner_block(graph: PeopleGraph) -> dict[str, Any] | None:
    if graph.owner is None:
        return None
    return {
        "person_id": graph.owner.person_id,
        "name": graph.owner.name,
        "identified": graph.owner.identified,
    }


def _bound_aliases(document: dict[str, Any], scanned: set[str]) -> dict[str, dict[str, Any]]:
    """Entries answering to more than one id, keyed by the id the scan finds them under.

    That is the person's own id. The scan reads the primary account only, so a person whose
    own id came from another account is found under their first bound primary id instead;
    the entry, and its own id, carry over whole.
    """
    bound: dict[str, dict[str, Any]] = {}
    for entry in people_entries(document):
        ids, primary = entry_ids(entry), primary_ids(entry)
        seen = ids[0] if ids[0] in primary else next(iter(primary), None)
        if len(ids) > 1 and seen in scanned:
            bound[seen] = entry
    return bound


def _entry_for(
    node: PersonNode, kept: dict[str, dict[str, Any]], bound: dict[str, Any] | None = None
) -> dict[str, Any]:
    person = node.evidence
    own = {PERSON_ID: bound[PERSON_ID]} if bound and bound.get(PERSON_ID) else {}
    return {
        "ids": copy.deepcopy(bound["ids"]) if bound else [person.person_id],
        **own,
        "name": person.name,
        "birth_date": _iso(person.birth_date),
        "inferred": {
            "tier": node.tier.value,
            "counts_reliable": node.counts_reliable,
            "evidence": _evidence_block(node),
            "links": [_link_block(link) for link in node.links],
        },
        # Copied, not referenced: one entry can name several ids, and two people sharing
        # one block would share every later edit to it.
        "confirmed": copy.deepcopy(kept.get(person.person_id)) or _blank_confirmed(),
    }


def _evidence_block(node: PersonNode) -> dict[str, Any]:
    person = node.evidence
    block = _evidence_numbers(node)
    if person.era_day_shares:
        block["era_day_share"] = {name: round(share, 3) for name, share in person.era_day_shares}
    return block


def _evidence_numbers(node: PersonNode) -> dict[str, Any]:
    person = node.evidence
    return {
        "count": person.count,
        "active_months": person.month_count,
        "first_month": _month(person.first_month),
        "last_month": _month(person.last_month),
        "span_years": round(person.span_years, 1),
        "onset": _month(person.onset),
        "concentration": round(person.concentration, 1),
        "continuity": round(person.continuity, 2),
    }


def _link_block(link: Link) -> dict[str, Any]:
    return {
        "kind": link.kind.value,
        "with": link.target_id,
        "confidence": round(link.confidence, 2),
        "via": link.via,
    }


def _blank_confirmed() -> dict[str, Any]:
    """The space reserved for the user, and never filled by the scan.

    Written out empty rather than omitted: an export is meant to be edited by
    hand, and a field nobody can see is a field nobody fills in.
    """
    return {"role": None, "links": [], "notes": None}


def _confirmed_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    kept: dict[str, dict[str, Any]] = {}
    for entry in people_entries(document):
        confirmed = entry.get("confirmed")
        if not isinstance(confirmed, dict):
            continue
        for person_id in entry_ids(entry):
            kept[person_id] = confirmed
    return kept


def _annotated_strangers(document: dict[str, Any], graph: PeopleGraph) -> list[dict[str, Any]]:
    """Entries the refresh no longer sees but somebody took the trouble to fill.

    Falling off the roster is a thing the library does — a person merged, a
    threshold moved, Immich unreachable for one call. None of those is a reason
    to delete an answer a person gave, so an entry carrying anything confirmed
    is carried forward exactly as it was. So is one holding an id another account
    reads: the primary scan cannot see it, and binding it was the owner's answer.
    """
    present = {node.evidence.person_id for node in graph.people}
    return [
        entry
        for entry in people_entries(document)
        if not present.intersection(entry_ids(entry))
        and (
            _has_content(entry.get("confirmed"))
            or entry.get("origin") == "manual"
            or len(primary_ids(entry)) < len(entry_ids(entry))
        )
    ]


def _has_content(confirmed: object) -> bool:
    return isinstance(confirmed, dict) and any(value for value in confirmed.values())


def _month(value: date | None) -> str | None:
    return f"{value:%Y-%m}" if value else None


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
