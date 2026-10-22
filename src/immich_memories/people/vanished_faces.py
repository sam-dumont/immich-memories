"""Keep a person's record when Immich changes the face id it names.

A store entry names its person by Immich face id. Immich can retire that id: two records
of the same person merged (one of them perhaps shared in from a household account),
re-clustered or deleted. The entry, with every relationship and answer on it, then names
nothing, and the next scan writes the person a second, empty record under their new face.

`heal_vanished_faces` runs after each scan, against the primary roster. An entry none of
whose ids the roster holds takes in the one other entry of the same name that holds a live
face, or else binds the one roster face carrying its name that no entry holds. It keeps its
own id either way, so every link, group and owner answer naming it still holds. Anything
less certain is marked for the People page to ask about. Two live ids never merge by name.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from immich_memories.config.models.resources import PRIMARY_ACCOUNT
from immich_memories.people.account_ids import entry_ids, ids_by_account, place_ids
from immich_memories.people.companion import DECLINED, people_entries

# Set on an entry whose faces are gone with no single face to follow; the People page asks.
NEEDS_RELINK = "needs_relink"
_MANUAL_PREFIX = "manual:"


@dataclass
class Healed:
    """What one heal did, by person name."""

    folded: list[str] = field(default_factory=list)
    relinked: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def heal_vanished_faces(document: dict[str, Any], roster: Mapping[str, str]) -> Healed:
    """Re-link every entry whose faces the primary roster (face id -> name) no longer holds."""
    healed = Healed()
    for entry in people_entries(document):
        entry.pop(NEEDS_RELINK, None)
    for orphan in [e for e in people_entries(document) if _orphaned(e, roster)]:
        name = str(orphan.get("name") or "")
        twins = _live_namesakes(document, orphan, roster)
        if len(twins) == 1:
            _fold(document, orphan, twins[0])
            healed.folded.append(name)
            continue
        face = _unheld_face(document, name, roster) if not twins else None
        if face is None:
            orphan[NEEDS_RELINK] = True
            healed.unresolved.append(name)
            continue
        groups = ids_by_account(orphan)
        groups.setdefault(PRIMARY_ACCOUNT, []).append(face)
        place_ids(orphan, groups, entry_ids(orphan)[0])
        healed.relinked.append(name)
    return healed


def _same_name(one: object, other: object) -> bool:
    return bool(str(one or "").strip()) and (
        str(one or "").strip().casefold() == str(other or "").strip().casefold()
    )


def _orphaned(entry: dict[str, Any], roster: Collection[str]) -> bool:
    """Every id the entry has is the primary's, and the primary holds none of them."""
    ids = entry_ids(entry)
    return (
        bool(ids)
        and set(ids_by_account(entry)) == {PRIMARY_ACCOUNT}
        and entry.get("origin") != "manual"
        and not any(face.startswith(_MANUAL_PREFIX) for face in ids)
        and not any(face in roster for face in ids)
    )


def _live_namesakes(
    document: dict[str, Any], orphan: dict[str, Any], roster: Collection[str]
) -> list[dict[str, Any]]:
    return [
        entry
        for entry in people_entries(document)
        if entry is not orphan
        and _same_name(entry.get("name"), orphan.get("name"))
        and any(face in roster for face in entry_ids(entry))
    ]


def _unheld_face(document: dict[str, Any], name: str, roster: Mapping[str, str]) -> str | None:
    held = {face for entry in people_entries(document) for face in entry_ids(entry)}
    named = [face for face, other in roster.items() if _same_name(other, name)]
    return named[0] if len(named) == 1 and named[0] not in held else None


def _fold(document: dict[str, Any], orphan: dict[str, Any], twin: dict[str, Any]) -> None:
    """The orphan takes the twin's faces and readings; the twin's answers join its own."""
    own = entry_ids(orphan)[0]
    twin_ids = entry_ids(twin)
    groups = ids_by_account(orphan)
    for account, faces in ids_by_account(twin).items():
        held = groups.setdefault(account, [])
        held.extend(face for face in faces if face not in held)
    place_ids(orphan, groups, own)
    orphan["inferred"] = twin.get("inferred")
    orphan["birth_date"] = orphan.get("birth_date") or twin.get("birth_date")
    _join_confirmed(orphan, twin)
    document["people"] = [entry for entry in document["people"] if entry is not twin]
    _point_at(document, set(twin_ids), own)


def _join_confirmed(orphan: dict[str, Any], twin: dict[str, Any]) -> None:
    mine = _confirmed(orphan)
    theirs = _confirmed(twin)
    joined = {**theirs, **{key: value for key, value in mine.items() if value}}
    links = [*(mine.get("links") or []), *(theirs.get("links") or [])]
    joined["links"] = [link for i, link in enumerate(links) if link not in links[:i]]
    orphan["confirmed"] = joined


def _confirmed(entry: dict[str, Any]) -> dict[str, Any]:
    confirmed = entry.get("confirmed")
    return confirmed if isinstance(confirmed, dict) else {}


def _point_at(document: dict[str, Any], old: set[str], new: str) -> None:
    """Every answer that named one of `old` names `new` instead."""
    for entry in people_entries(document):
        for block in ("confirmed", "inferred"):
            _point_links_at(entry.get(block), old, new)
    owner = document.get("owner")
    if isinstance(owner, dict) and owner.get("person_id") in old:
        owner["person_id"] = new
    for answer in document.get(DECLINED) or []:
        if isinstance(answer, dict) and answer.get("person_id") in old:
            answer["person_id"] = new
    _point_groups_at(document, old, new)


def _point_links_at(section: object, old: set[str], new: str) -> None:
    links = section.get("links") if isinstance(section, dict) else None
    for link in links if isinstance(links, list) else []:
        if isinstance(link, dict) and link.get("with") in old:
            link["with"] = new


def _point_groups_at(document: dict[str, Any], old: set[str], new: str) -> None:
    from immich_memories.api.person_expression import PersonExpression

    for group in document.get("groups") or []:
        try:
            expression = PersonExpression.from_dict(group["expression"])
        except (KeyError, TypeError, ValueError):
            continue
        group["expression"] = expression.map_leaves(
            lambda leaf: new if leaf in old else leaf
        ).to_dict()
