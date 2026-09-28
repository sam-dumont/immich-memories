"""The people registry's rows, read and written as the document every caller already speaks.

The document is the shape `people.yaml` had: a header (version, generated, owner) and a list
of person entries with `ids`, `name`, `birth_date`, `inferred`, `confirmed` and `origin`.
An entry whose ids come from a second Immich account adds `accounts`, id to account name;
an id it does not list is the primary account's, so a one-account registry never has one.
Callers edit that document; this module is the only code that knows how it maps to rows.
A write replaces the whole registry inside the caller's transaction, after `lock_registry`,
so two writers queue on the registry row instead of dropping each other's change.
"""

from __future__ import annotations

import operator
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db import now_db, upsert
from immich_memories.db.tables import (
    people,
    people_aliases,
    people_registry,
    people_relationships,
)

REGISTRY = "default"

_PERSON_KEYS = ("ids", "accounts", "name", "birth_date", "origin", "inferred", "confirmed")
_LINK_KEYS = ("kind", "with", "reverse", "decision")


def lock_registry(connection: Connection) -> None:
    """Hold the registry row until the transaction ends.

    SQLite already serialises writers at `BEGIN IMMEDIATE`; PostgreSQL needs the row lock,
    and the row has to exist before anything can lock it.
    """
    upsert(connection, people_registry, [{"registry": REGISTRY}], ["registry"], update=())
    connection.execute(
        sa.select(people_registry.c.registry)
        .where(people_registry.c.registry == REGISTRY)
        .with_for_update()
    )


def read_document(connection: Connection) -> dict[str, Any]:
    """The registry as a document, or `{}` when nothing was ever written."""
    header = connection.execute(
        sa.select(people_registry.c.header).where(people_registry.c.registry == REGISTRY)
    ).scalar_one_or_none()
    rows = connection.execute(sa.select(people).order_by(people.c.position)).mappings().all()
    if not header and not rows:
        return {}
    aliases = _grouped(connection, people_aliases, operator.itemgetter("alias_id", "account"))
    links = _grouped(connection, people_relationships, _link)
    document = dict(header or {})
    document["people"] = [
        _entry(
            row,
            aliases.get(row["person_id"], [(row["person_id"], None)]),
            links.get(row["person_id"], []),
        )
        for row in rows
    ]
    return document


def write_document(connection: Connection, document: dict[str, Any]) -> None:
    """Replace the registry with `document`, whose entries are already validated.

    Every id must be a string and belong to one entry; the tables' keys refuse anything else.
    """
    connection.execute(sa.delete(people_relationships))
    connection.execute(sa.delete(people_aliases))
    connection.execute(sa.delete(people))
    header = {key: value for key, value in document.items() if key != "people"}
    upsert(
        connection,
        people_registry,
        [{"registry": REGISTRY, "header": header, "updated_at": now_db()}],
        ["registry"],
    )
    person_rows, alias_rows, link_rows = _rows(document.get("people") or [])
    for table, rows in (
        (people, person_rows),
        (people_aliases, alias_rows),
        (people_relationships, link_rows),
    ):
        if rows:
            connection.execute(sa.insert(table), rows)


def _rows(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    person_rows: list[dict[str, Any]] = []
    alias_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        person_id = entry["ids"][0]
        confirmed = entry.get("confirmed")
        block = dict(confirmed) if isinstance(confirmed, dict) else None
        links = (block or {}).pop("links", None) or []
        person_rows.append(
            {
                "person_id": person_id,
                "position": position,
                "name": entry.get("name"),
                "birth_date": entry.get("birth_date"),
                "origin": entry.get("origin"),
                "inferred": entry.get("inferred"),
                "confirmed": block,
                "extra": {key: value for key, value in entry.items() if key not in _PERSON_KEYS}
                or None,
            }
        )
        accounts = entry.get("accounts") or {}
        alias_rows.extend(
            {
                "alias_id": alias,
                "person_id": person_id,
                "position": index,
                "account": accounts.get(alias),
            }
            for index, alias in enumerate(entry["ids"])
        )
        link_rows.extend(
            {
                "person_id": person_id,
                "position": index,
                "kind": link.get("kind"),
                "target_id": link.get("with"),
                "reverse": link.get("reverse"),
                "decision": link.get("decision"),
                "extra": {key: value for key, value in link.items() if key not in _LINK_KEYS}
                or None,
            }
            for index, link in enumerate(links)
        )
    return person_rows, alias_rows, link_rows


def _grouped(connection: Connection, table: sa.Table, shape: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    rows = connection.execute(sa.select(table).order_by(table.c.person_id, table.c.position))
    for row in rows.mappings():
        grouped[row["person_id"]].append(shape(row))
    return grouped


def _link(row: Any) -> dict[str, Any]:
    link: dict[str, Any] = {"kind": row["kind"], "with": row["target_id"]}
    for key in ("reverse", "decision"):
        if row[key] is not None:
            link[key] = row[key]
    link.update(row["extra"] or {})
    return link


def _entry(
    row: Any, aliases: list[tuple[str, str | None]], links: list[dict[str, Any]]
) -> dict[str, Any]:
    entry: dict[str, Any] = {"ids": [alias for alias, _ in aliases]}
    accounts = {alias: account for alias, account in aliases if account is not None}
    if accounts:
        entry["accounts"] = accounts
    entry |= {"name": row["name"], "birth_date": row["birth_date"]}
    if row["inferred"] is not None:
        entry["inferred"] = row["inferred"]
    block = dict(row["confirmed"] or {})
    role, notes = block.pop("role", None), block.pop("notes", None)
    entry["confirmed"] = {"role": role, "links": links, "notes": notes} | block
    if row["origin"] is not None:
        entry["origin"] = row["origin"]
    entry.update(row["extra"] or {})
    return entry
