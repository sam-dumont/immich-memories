"""Keep a person's record when Immich changes the face id it names.

A store entry names its person by Immich face id. Immich can retire that id: two records
of the same person merged (one of them perhaps shared in from a household account),
re-clustered or deleted. The entry, with every relationship and answer on it, then names
nothing, and the next scan writes the person a second, empty record under their new face.

`heal_store` runs wherever the app reads the primary roster anyway: a scan, the People
page, a film's start, automation's discovery. An entry none of whose ids the roster holds
takes in the one other entry of the same name that holds a live face, or else binds the one
roster face carrying its name that no entry holds. It keeps its own id either way, so every
link, group and owner answer naming it still holds, and lists the faces Immich dropped as
retired so nothing asks for them again. Anything less certain is marked for the People page
to ask about. Two live ids never merge by name.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from immich_memories.config.models.resources import PRIMARY_ACCOUNT
from immich_memories.people.account_ids import (
    RETIRED,
    entry_ids,
    ids_by_account,
    live_ids_by_account,
    place_ids,
)
from immich_memories.people.companion import (
    DECLINED,
    edit_registry,
    load_document,
    people_entries,
)

if TYPE_CHECKING:
    from immich_memories.db import Store

logger = logging.getLogger(__name__)

# Set on an entry whose faces are gone with no single face to follow; the People page asks.
NEEDS_RELINK = "needs_relink"
_MANUAL_PREFIX = "manual:"


@dataclass
class Healed:
    """What one heal did, by person name."""

    folded: list[str] = field(default_factory=list)
    relinked: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def heal_store(
    store: Store,
    roster: Mapping[str, str],
    count: Callable[[str], int] | None = None,
    *,
    scan: bool = False,
) -> Healed:
    """Save `heal_vanished_faces` against a primary roster the caller has already read.

    An empty roster is a failed read or an empty library, never proof that everybody's face
    is gone: it changes nothing. With `count` (face id -> pictures), a face Immich still
    lists with no pictures counts as gone too, when a face of the same name has pictures
    (`empty_faces`). A heal that changes nothing writes nothing.
    """
    if not roster:
        return Healed()
    if count is not None:
        empty = empty_faces(load_document(store), roster, count)
        roster = {face: name for face, name in roster.items() if face not in empty}
    return edit_registry(store, lambda document: heal_vanished_faces(document, roster, scan=scan))


def empty_faces(
    document: dict[str, Any], roster: Mapping[str, str], count: Callable[[str], int]
) -> frozenset[str]:
    """Primary faces Immich still lists with no pictures, beside a same-name face that has some.

    A merge can leave an empty record behind instead of deleting it. Only a store person
    whose name another roster face carries is counted, so a library pays a few count reads,
    not one per person; a face with nothing better to follow is never called empty.
    """
    pictures = functools.cache(lambda face: _pictures(count, face))
    by_name: dict[str, list[str]] = {}
    for face, name in roster.items():
        if name.strip():
            by_name.setdefault(name.strip().casefold(), []).append(face)
    empty: set[str] = set()
    for entry in people_entries(document):
        faces = [f for f in live_ids_by_account(entry).get(PRIMARY_ACCOUNT, []) if f in roster]
        name = str(entry.get("name") or "").strip().casefold()
        others = [face for face in by_name.get(name, []) if face not in faces]
        if not faces or not others or any(pictures(face) for face in faces):
            continue
        if any(pictures(face) for face in others):
            empty.update(faces)
            empty.update(face for face in others if not pictures(face))
    return frozenset(empty)


def picture_counter(client: Any) -> Callable[[str], int]:
    """`client`'s picture count for a face (`/people/{id}/statistics`), looked up only when
    the heal needs one; a count it can't read leaves the face alone (`_pictures`)."""

    def count(face: str) -> int:
        return int(client.get_person_asset_count(face))

    return count


def _pictures(count: Callable[[str], int], face: str) -> int:
    """A face's picture count; one that can't be read counts as having pictures."""
    try:
        return count(face)
    except Exception as error:  # noqa: BLE001 - an unreadable count never retires a face
        logger.warning("Could not count a person's pictures (%s)", type(error).__name__)
        return 1


def heal_vanished_faces(
    document: dict[str, Any], roster: Mapping[str, str], *, scan: bool = False
) -> Healed:
    """Re-link every entry whose faces the primary roster (face id -> name) no longer holds.

    A scan re-asks every flag. Anywhere else (the People page, a film, automation) only an
    entry Immich has a namesake for, that still can't be followed, is flagged: a store that
    holds people this library never had (an import, a key for another user) stays quiet,
    and a film naming one of them still stops with the advice.
    """
    healed = Healed()
    if scan:
        for entry in people_entries(document):
            entry.pop(NEEDS_RELINK, None)
    for orphan in [e for e in people_entries(document) if _orphaned(e, roster)]:
        name = str(orphan.get("name") or "")
        twins = _live_namesakes(document, orphan, roster)
        if len(twins) == 1:
            orphan.pop(NEEDS_RELINK, None)
            _retire(orphan, roster)
            _fold(document, orphan, twins[0])
            healed.folded.append(name)
            continue
        face = _unheld_face(document, name, roster) if not twins else None
        if face is None:
            if scan or any(_same_name(other, name) for other in roster.values()):
                orphan[NEEDS_RELINK] = True
            healed.unresolved.append(name)
            continue
        orphan.pop(NEEDS_RELINK, None)
        _retire(orphan, roster)
        groups = ids_by_account(orphan)
        groups.setdefault(PRIMARY_ACCOUNT, []).append(face)
        place_ids(orphan, groups, entry_ids(orphan)[0])
        healed.relinked.append(name)
    return healed


def _retire(entry: dict[str, Any], roster: Collection[str]) -> None:
    """List the entry's faces the roster no longer holds as retired; they stay its ids."""
    gone = [face for face in entry_ids(entry) if face not in roster]
    entry[RETIRED] = list(dict.fromkeys([*(entry.get(RETIRED) or []), *gone]))


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
