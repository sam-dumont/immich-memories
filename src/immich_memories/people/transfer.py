"""`people.yaml` as an export and import format, and the one-time import of the legacy file.

The store holds the registry. A YAML document is what `people export` writes and
`people import` reads: the same shape the file always had, with every id preserved. An
import is validated before anything is written, so a typo cannot half-replace a roster.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from immich_memories.db import Store
from immich_memories.db.legacy_import import ImportOutcome
from immich_memories.people.registry_store import lock_registry, read_document, write_document

LEGACY_FILE = "people.yaml"

EXPORT_HEADER = """\
# The people registry, exported from the immich-memories store.
#
# `immich-memories people import --from <this file>` replaces the registry with it.
# Everything under `inferred:` is recomputed by `immich-memories people scan`; everything
# under `confirmed:` is yours, and the scan copies it through untouched.
"""

_SCALARS = (str, int, float)


class PeopleImportError(ValueError):
    """A document that cannot become the registry, with every reason it cannot."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass
class _Checked:
    document: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    dropped: int = 0


def export_yaml(store: Store) -> str:
    """The registry as a YAML document, the shape `people.yaml` always had."""
    with store.connect() as connection:
        document = read_document(connection)
    body = yaml.dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return EXPORT_HEADER + body


def parse_yaml(text: str) -> object:
    """A YAML document, or PeopleImportError when it does not parse."""
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PeopleImportError([f"not valid YAML: {exc}"]) from None


def import_document(store: Store, document: object, *, replace: bool = False) -> int:
    """Replace the registry with `document` and return how many people it holds.

    Nothing is written unless every entry is valid: ids are kept exactly, and an id may
    belong to one person only. A registry that already holds people is only replaced
    when `replace` says so, because an old export would overwrite newer answers.
    """
    checked = _check(document)
    if checked.problems:
        raise PeopleImportError(checked.problems)
    with store.begin() as connection:
        lock_registry(connection)
        held = len(read_document(connection).get("people", []))
        if held and not replace:
            raise PeopleImportError(
                [f"the registry already holds {held} people; pass --replace to overwrite them"]
            )
        write_document(connection, checked.document)
    return len(checked.document.get("people", []))


def import_legacy(store: Store, home: Path) -> ImportOutcome:
    """Bring `home/people.yaml` into the store without touching the file.

    A person the store does not know yet is added whole. A person it already knows keeps
    the store's record, except that confirmed answers fill a confirmed block the store has
    left empty: the owner's answers are never lost to an import. A second run imports 0.
    """
    path = home / LEGACY_FILE
    if not path.exists():
        return ImportOutcome(str(path), 0, 0, ("no people.yaml",))
    try:
        checked = _check(parse_yaml(path.read_text()))
    except (OSError, PeopleImportError) as exc:
        return ImportOutcome(str(path), 0, 0, (f"not readable: {exc}",))
    with store.begin() as connection:
        lock_registry(connection)
        standing = read_document(connection)
        imported, skipped = _merge(standing, checked.document)
        if imported:
            write_document(connection, standing)
    return ImportOutcome(str(path), imported, skipped + checked.dropped, tuple(checked.problems))


def _merge(standing: dict[str, Any], legacy: dict[str, Any]) -> tuple[int, int]:
    if not standing.get("people"):
        standing.clear()
        standing.update(copy.deepcopy(legacy))
        count = len(standing.get("people", []))
        return count, 0
    by_id = {person_id: entry for entry in standing["people"] for person_id in entry["ids"]}
    imported = skipped = 0
    for entry in legacy.get("people", []):
        known = next((by_id[i] for i in entry["ids"] if i in by_id), None)
        if known is None:
            standing["people"].append(copy.deepcopy(entry))
            by_id.update(dict.fromkeys(entry["ids"], standing["people"][-1]))
            imported += 1
        elif _answered(entry) and not _answered(known):
            known["confirmed"] = copy.deepcopy(entry["confirmed"])
            imported += 1
        else:
            skipped += 1
    return imported, skipped


def _answered(entry: dict[str, Any]) -> bool:
    confirmed = entry.get("confirmed")
    return isinstance(confirmed, dict) and any(confirmed.values())


def _check(document: object) -> _Checked:
    if document is None:
        return _Checked({})
    if not isinstance(document, dict):
        return _Checked({}, ["the document is not a mapping"])
    raw_people = document.get("people", [])
    if not isinstance(raw_people, list):
        return _Checked({}, ["`people` is not a list"])
    header = {key: _plain(value) for key, value in document.items() if key != "people"}
    checked = _Checked(header | {"people": []})
    seen: set[str] = set()
    for index, raw in enumerate(raw_people):
        entry, problem = _entry(raw, seen)
        if problem is not None:
            checked.problems.append(f"people[{index}]: {problem}")
            checked.dropped += 1
            continue
        seen.update(entry["ids"])
        checked.document["people"].append(entry)
    return checked


def _entry(raw: object, seen: set[str]) -> tuple[dict[str, Any], str | None]:
    if not isinstance(raw, dict):
        return {}, "not a mapping"
    ids = raw.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, _SCALARS) for i in ids):
        return {}, "`ids` must be a non-empty list of ids"
    person_ids = [str(i) for i in ids]
    if len(set(person_ids)) != len(person_ids) or seen.intersection(person_ids):
        return {}, f"an id is listed twice: {', '.join(person_ids)}"
    problem = _shape_problem(raw)
    if problem is not None:
        return {}, problem
    entry = {key: _plain(value) for key, value in raw.items()}
    entry["ids"] = person_ids
    for key in ("name", "origin"):
        if entry.get(key) is not None:
            entry[key] = str(entry[key])
    confirmed = entry.get("confirmed")
    if isinstance(confirmed, dict):
        confirmed["links"] = [_link(link) for link in confirmed.get("links") or []]
    return entry, None


def _shape_problem(raw: dict[str, Any]) -> str | None:
    for key in ("name", "origin"):
        if raw.get(key) is not None and not isinstance(raw[key], _SCALARS):
            return f"`{key}` must be text"
    if raw.get("birth_date") is not None and not isinstance(raw["birth_date"], str | date):
        return "`birth_date` must be a date"
    for key in ("inferred", "confirmed"):
        if raw.get(key) is not None and not isinstance(raw[key], dict):
            return f"`{key}` must be a mapping"
    links = (raw.get("confirmed") or {}).get("links")
    if links is not None and not (
        isinstance(links, list) and all(isinstance(link, dict) for link in links)
    ):
        return "`confirmed.links` must be a list of mappings"
    return None


def _link(link: dict[str, Any]) -> dict[str, Any]:
    text_keys = {"kind", "with", "reverse", "decision"}
    return {
        key: str(value) if key in text_keys and value is not None else value
        for key, value in link.items()
    }


def _plain(value: Any) -> Any:
    """A value the store's JSON columns can hold: YAML's unquoted dates become ISO text."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
