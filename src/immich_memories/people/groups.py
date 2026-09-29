"""Saved people expressions: a label `generate --group` resolves like `--people-expression`.

A saved group is a label plus a `PersonExpression` (`api/person_expression.py`) over
canonical person ids — the ids `people show` lists, the same grammar and size limits
`--people-expression` already validates. No name is copied into it and no group nests
inside another: resolution reads the people store at generate time, exactly as
`--people-expression` does, so a rename or a merge in the store is seen immediately.

Groups live in the same registry document as `people:` (`people/registry_store.py`), so
`people export`/`people import` round-trip them next to the people they may or may not
still name.
"""

from __future__ import annotations

from dataclasses import dataclass

from immich_memories.api.person_expression import PersonExpression
from immich_memories.db import Store
from immich_memories.people.registry_store import lock_registry, read_document, write_document


@dataclass(frozen=True)
class SavedGroup:
    label: str
    expression: PersonExpression


def list_groups(store: Store) -> list[SavedGroup]:
    """Every saved group, in the order they were added."""
    with store.connect() as connection:
        document = read_document(connection)
    return _parsed(document)


def group_expression(store: Store, label: str) -> PersonExpression:
    """The expression saved under `label`.

    Raises `ValueError` naming what is saved when `label` is not one of them, so
    `generate --group` fails before any picture is read.
    """
    groups = list_groups(store)
    found = next((saved for saved in groups if saved.label == label), None)
    if found is not None:
        return found.expression
    known = ", ".join(saved.label for saved in groups) or "none saved yet"
    raise ValueError(f"no saved group named {label!r}; known groups: {known}")


def add_group(store: Store, label: str, expression: PersonExpression) -> None:
    """Save `expression` under `label`. A label already in use is refused, never replaced."""
    if not label.strip():
        raise ValueError("a group label cannot be empty")
    with store.begin() as connection:
        lock_registry(connection)
        document = read_document(connection)
        groups = document.setdefault("groups", [])
        if any(saved["label"] == label for saved in groups):
            msg = f"a saved group named {label!r} already exists; `people group rm` it first"
            raise ValueError(msg)
        groups.append({"label": label, "expression": expression.to_dict()})
        write_document(connection, document)


def remove_group(store: Store, label: str) -> None:
    """Remove a saved group. Never touches the people it named."""
    with store.begin() as connection:
        lock_registry(connection)
        document = read_document(connection)
        groups = document.get("groups") or []
        remaining = [saved for saved in groups if saved["label"] != label]
        if len(remaining) == len(groups):
            raise ValueError(f"no saved group named {label!r}")
        document["groups"] = remaining
        write_document(connection, document)


def _parsed(document: dict[str, object]) -> list[SavedGroup]:
    raw = document.get("groups")
    if not isinstance(raw, list):
        return []
    return [
        SavedGroup(str(saved["label"]), PersonExpression.from_dict(saved["expression"]))
        for saved in raw
        if isinstance(saved, dict) and "label" in saved and "expression" in saved
    ]
