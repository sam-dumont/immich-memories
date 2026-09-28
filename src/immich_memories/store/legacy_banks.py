"""Bring the JSON banks into the store, once, without touching the files.

Three kinds of file, found where the current code would have written them:

- `structure-banks/audience-verdicts.private.json`: answers by answerer and evidence key,
  and hold slots by picture.
- `structure-banks/<case>/memory-worthy.private.json` and `thesis-fit.private.json`: block vote
  banks, scoped by the case directory's name.
- `<film>.owner-edits-<id>.private.json` beside a rendered film in the output directory.

`structure-banks/` is looked for under the default cache directory and under the directory a
configured `editorial.annotation_database` sits in (`EditorialConfig.resolve_bank_root`).
Every key is kept as written. A row the store already holds keeps the store's value, with one
exception the audience gate demands: a legacy hold stricter than the store's hold in the same
slot, cast under the same prompt, tightens it. A hold only ever tightens. The files are read,
never written, and a second run imports nothing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from immich_memories.analysis import editorial_shareability as _share
from immich_memories.db import Store, to_db
from immich_memories.db.legacy_import import ImportOutcome
from immich_memories.db.tables import (
    audience_answers,
    audience_holds,
    owner_edits,
    vote_bank_entries,
)
from immich_memories.store.batches import id_in, in_chunks, insert_rows, upsert_rows
from immich_memories.store.legacy_verify import verify_rows
from immich_memories.store.vote_banks import ROW_SECTIONS

logger = logging.getLogger(__name__)

AUDIENCE_FILE = "audience-verdicts.private.json"
VOTE_BANKS = ("memory-worthy", "thesis-fit")
_OWNER_EDIT_MARK = ".owner-edits-"


def bank_roots(home: Path) -> tuple[list[Path], list[Path]]:
    """The `structure-banks/` directories and film output directories the current code uses."""
    roots = [home / "cache"]
    outputs = [_expand(home, "~/Videos/Memories")]
    # Loaded even when the home has no config.yaml (a missing file reads as empty): the
    # Docker image names its output directory in the environment and ships no file. The
    # default directory stays a candidate, so films reviewed before a move still count.
    try:
        from immich_memories.config_loader import Config

        # stored={}: only the file's paths matter here, and reading saved settings would open
        # the default store under `home`, not the one being imported into.
        config = Config.from_yaml(home / "config.yaml", stored={})
        cache = _expand(home, config.cache.directory)
        roots += [cache, config.editorial.resolve_bank_root(cache)]
        outputs.append(_expand(home, config.output.directory))
    except Exception as exc:  # WHY: a config that no longer loads still has default files
        logger.warning("config.yaml unreadable for the import (%s): default paths only", exc)
    return _existing([root / "structure-banks" for root in roots]), _existing(outputs)


def _expand(home: Path, directory: str) -> Path:
    """`~` is the home `~/.immich-memories` sits in, so an import of a copied home stays in it."""
    if directory == "~" or directory.startswith("~/"):
        return home.parent / directory[2:]
    return Path(directory)


def _existing(paths: Sequence[Path]) -> list[Path]:
    seen: dict[Path, Path] = {}
    for path in paths:
        if path.is_dir():
            seen.setdefault(path.resolve(), path)
    return list(seen.values())


def import_legacy(store: Store, home: Path) -> ImportOutcome:
    """Copy every legacy bank entry and owner edit the store does not hold yet.

    `home` is the `~/.immich-memories` directory. Counts are entries: one answer, one hold
    slot, one vote bank entry, one owner edit.
    """
    banks, outputs = bank_roots(home)
    imported = skipped = 0
    notes: list[str] = []
    for directory in banks:
        for done, left, said in (
            _import_audience(store, directory / AUDIENCE_FILE),
            *(_import_votes(store, path) for path in _vote_files(directory)),
        ):
            imported, skipped = imported + done, skipped + left
            notes += said
    for output in outputs:
        done, left, said = _import_owner_edits(store, output)
        imported, skipped = imported + done, skipped + left
        notes += said
    return ImportOutcome("json-banks", imported, skipped, tuple(notes))


Counted = tuple[int, int, list[str]]


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text()), None
    except (OSError, ValueError) as exc:
        return None, f"{path}: unreadable ({type(exc).__name__}), left as it is"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _import_audience(store: Store, path: Path) -> Counted:
    if not path.is_file():
        return 0, 0, []
    stored, problem = _read_json(path)
    if problem or not isinstance(stored, Mapping):
        return 0, 0, [problem or f"{path}: not a JSON object, left as it is"]
    notes = [
        f"{path}: top-level key {key!r} not imported"
        for key in stored
        if key not in ("answers", "holds")
    ]
    rows, slots = _audience_rows(stored)
    done, left = _insert_new(store, audience_answers, rows, ("answerer", "evidence_key"))
    added, tightened, kept = _import_holds(store, slots)
    if tightened:
        notes.append(f"{path}: {tightened} stricter legacy hold(s) tightened the store's")
    return done + added + tightened, left + kept, notes


def _audience_rows(
    stored: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], Any]]:
    answers = _mapping(stored.get("answers"))
    rows = [
        {"answerer": answerer, "evidence_key": key, "record": record}
        for answerer, by_key in answers.items()
        if isinstance(by_key, Mapping)
        for key, record in by_key.items()
    ]
    holds = _mapping(stored.get("holds"))
    slots = {
        (asset_id, slot): hold
        for asset_id, by_slot in holds.items()
        if isinstance(by_slot, Mapping)
        for slot, hold in by_slot.items()
    }
    return rows, slots


def _import_holds(store: Store, slots: dict[tuple[str, str], Any]) -> tuple[int, int, int]:
    """New slots go in; a slot the store has is replaced only by a stricter hold of its prompt."""
    with store.begin() as connection:
        existing = {}
        ids = sorted({asset_id for asset_id, _slot in slots})
        for chunk in in_chunks(connection, ids):
            for row in connection.execute(
                sa.select(audience_holds).where(id_in(connection, audience_holds.c.asset_id, chunk))
            ):
                existing[(row.asset_id, row.slot)] = row.hold
        new = [key for key in slots if key not in existing]
        stricter = [key for key in slots if key in existing and _tighter(slots[key], existing[key])]
        insert_rows(
            connection,
            audience_holds,
            [{"asset_id": a, "slot": s, "hold": slots[(a, s)]} for a, s in new],
        )
        upsert_rows(
            connection,
            audience_holds,
            [{"asset_id": a, "slot": s, "hold": slots[(a, s)]} for a, s in stricter],
            ("asset_id", "slot"),
        )
    return len(new), len(stricter), len(slots) - len(new) - len(stricter)


def _tighter(legacy: Any, current: Any) -> bool:
    if not (isinstance(legacy, Mapping) and isinstance(current, Mapping)):
        return False
    if legacy.get("text_version") != current.get("text_version"):
        return False
    old, now = legacy.get("verdict"), current.get("verdict")
    if old not in _share.VERDICTS or now not in _share.VERDICTS:
        return False
    return _share.VERDICTS.index(old) > _share.VERDICTS.index(now)


def _vote_files(directory: Path) -> Iterator[Path]:
    for case in sorted(p for p in directory.iterdir() if p.is_dir()):
        for bank in VOTE_BANKS:
            path = case / f"{bank}.private.json"
            if path.is_file():
                yield path


def _import_votes(store: Store, path: Path) -> Counted:
    stored, problem = _read_json(path)
    if problem or not isinstance(stored, Mapping):
        return 0, 0, [problem or f"{path}: not a JSON object, left as it is"]
    rows = _vote_rows(path, stored)
    done, left = _insert_new(
        store, vote_bank_entries, rows, ("bank", "scope", "section", "entry_key")
    )
    return done, left, []


def _vote_rows(path: Path, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
    bank, scope = path.name.removesuffix(".private.json"), path.parent.name
    rows = []
    for key, value in stored.items():
        if key in ROW_SECTIONS and isinstance(value, Mapping):
            rows += [_vote_row(bank, scope, key, name, row) for name, row in value.items()]
        else:
            rows.append(_vote_row(bank, scope, "", key, value))
    return rows


def _vote_row(bank: str, scope: str, section: str, key: str, value: Any) -> dict[str, Any]:
    return {"bank": bank, "scope": scope, "section": section, "entry_key": key, "value": value}


def _import_owner_edits(store: Store, output: Path) -> Counted:
    rows, notes = _owner_edit_rows(output)
    done, left = _insert_new(store, owner_edits, rows, ("edit_id",))
    return done, left, notes


def _owner_edit_files(output: Path) -> list[Path]:
    return sorted(output.rglob(f"*{_OWNER_EDIT_MARK}*.private.json"))


def _owner_edit_rows(output: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for path in _owner_edit_files(output):
        record, problem = _read_json(path)
        if problem or not isinstance(record, Mapping):
            notes.append(problem or f"{path}: not a JSON object, left as it is")
            continue
        stem, edit_id = path.name.removesuffix(".private.json").rsplit(_OWNER_EDIT_MARK, 1)
        rows.append(
            {
                "edit_id": edit_id,
                "film_stem": stem,
                "attempt_id": None,
                "record": record,
                "recorded_at": to_db(datetime.fromtimestamp(path.stat().st_mtime, UTC)),
            }
        )
    return rows, notes


def _insert_new(
    store: Store, table: sa.Table, rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> tuple[int, int]:
    """Insert the rows whose key the store lacks; a key seen twice keeps its first row."""
    unique = list({tuple(row[k] for k in keys): row for row in reversed(rows)}.values())[::-1]
    if not unique:
        return 0, len(rows)
    with store.begin() as connection:
        have = _keys_present(connection, table, keys, unique)
        new = [row for row in unique if tuple(row[k] for k in keys) not in have]
        insert_rows(connection, table, new)
    return len(new), len(rows) - len(new)


def _keys_present(connection, table: sa.Table, keys: Sequence[str], rows) -> set[tuple]:
    """Which of these rows' keys the table holds, narrowed by the first key column."""
    first = table.c[keys[0]]
    have: set[tuple] = set()
    for chunk in in_chunks(connection, sorted({str(row[keys[0]]) for row in rows})):
        found = connection.execute(
            sa.select(*(table.c[k] for k in keys)).where(id_in(connection, first, chunk))
        )
        have.update(tuple(row) for row in found)
    return have


def legacy_sources(home: Path) -> list[Path]:
    """Every bank file and owner edit `import_legacy` reads under `home`."""
    banks, outputs = bank_roots(home)
    found: list[Path] = []
    for directory in banks:
        audience = directory / AUDIENCE_FILE
        found += [audience] if audience.is_file() else []
        found += list(_vote_files(directory))
    for output in outputs:
        found += _owner_edit_files(output)
    return found


def verify_legacy(store: Store, home: Path) -> list[str]:
    """Every legacy bank entry the store lacks or holds otherwise.

    Owner edits compare exactly. A hold passes when the store's is the same or, under the
    same prompt, stricter: the import may tighten a hold, never loosen one.
    """
    banks, outputs = bank_roots(home)
    problems: list[str] = []
    with store.connect() as connection:
        for directory in banks:
            problems += _verify_audience(connection, directory / AUDIENCE_FILE)
            for path in _vote_files(directory):
                stored, problem = _read_json(path)
                if problem or not isinstance(stored, Mapping):
                    problems.append(problem or f"{path}: not a JSON object")
                    continue
                keys = ("bank", "scope", "section", "entry_key")
                problems += verify_rows(
                    connection, vote_bank_entries, keys, _vote_rows(path, stored)
                )
        for output in outputs:
            rows, notes = _owner_edit_rows(output)
            problems += notes
            problems += verify_rows(connection, owner_edits, ("edit_id",), rows, exact=True)
    return problems


def _verify_audience(connection: sa.Connection, path: Path) -> list[str]:
    if not path.is_file():
        return []
    stored, problem = _read_json(path)
    if problem or not isinstance(stored, Mapping):
        return [problem or f"{path}: not a JSON object"]
    rows, slots = _audience_rows(stored)
    problems = verify_rows(connection, audience_answers, ("answerer", "evidence_key"), rows)
    held = {}
    ids = sorted({asset_id for asset_id, _slot in slots})
    for chunk in in_chunks(connection, ids):
        query = sa.select(audience_holds).where(id_in(connection, audience_holds.c.asset_id, chunk))
        held.update({(row.asset_id, row.slot): row.hold for row in connection.execute(query)})
    for (asset_id, slot), hold in slots.items():
        if (asset_id, slot) not in held:
            problems.append(f"audience_holds {asset_id}/{slot}: missing")
        elif held[(asset_id, slot)] != hold and not _tighter(held[(asset_id, slot)], hold):
            problems.append(f"audience_holds {asset_id}/{slot}: looser than the legacy hold")
    return problems
