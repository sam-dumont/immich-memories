"""Merge Immich people, asset counts and birthdays across a household's selected accounts.

Two accounts on one server give the same real person two Immich ids. Discovery's detectors
(`calendar_detectors.py`, `event_detectors.py`) still take one plain list of duck-typed
people (`.id`, `.name`, `.birth_date`, `.thumbnail_path`) and one asset-count dict keyed
by that same id — this is where per-account reads become that one merged view, using the
same store aliases `--accounts` resolution already reads (`analysis/person_resolution.py`).

Pure functions over typed values: no network and no store I/O here. The caller reads the
store document and each account once, and hands the results in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.person_resolution import StorePerson
from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import people_entries

if TYPE_CHECKING:
    from immich_memories.api.native_sharing import NativePeople


@dataclass(frozen=True)
class MergedPerson:
    """One real person, however many accounts' rosters found them."""

    id: str
    name: str
    birth_date: date | None
    thumbnail_path: str | None


def canonical_person_map(
    store: Sequence[StorePerson],
    *,
    native: NativePeople | None = None,
) -> dict[tuple[str, str], str]:
    """Every store alias's (account, face id) to the canonical person id that owns it."""
    result = {
        (alias.account, alias.face_id): person.person_id
        for person in store
        for alias in person.aliases
    }

    if native is not None:
        for person in store:
            for alias in person.aliases:
                origin = native.origins.get(alias.face_id)
                if origin is None or origin != native.binding_servers.get(alias.account):
                    continue
                result.update(
                    ((account, alias.face_id), person.person_id)
                    for account in native.scopes.get(alias.face_id, ())
                )
    return result


def merge_people(
    per_account: Mapping[str, Sequence[Any]],
    canon: Mapping[tuple[str, str], str],
) -> list[MergedPerson]:
    """One row per real person: the store's aliases fold every account's roster into one.

    A face the store has not bound to anyone keeps its own account's id, unmerged. The
    first account to report a field wins it; a later account only fills in what is missing.
    """
    merged: dict[str, MergedPerson] = {}
    for account, people in per_account.items():
        for person in people:
            canonical_id = canon.get((account, person.id), person.id)
            merged[canonical_id] = _folded(canonical_id, person, merged.get(canonical_id))
    return list(merged.values())


def _folded(canonical_id: str, person: Any, existing: MergedPerson | None) -> MergedPerson:
    birth_date = _as_date(getattr(person, "birth_date", None))
    thumbnail = getattr(person, "thumbnail_path", None)
    if existing is None:
        return MergedPerson(canonical_id, person.name or "", birth_date, thumbnail)
    return MergedPerson(
        canonical_id,
        existing.name or (person.name or ""),
        existing.birth_date or birth_date,
        existing.thumbnail_path or thumbnail,
    )


def merge_counts(
    per_account: Mapping[str, Mapping[str, int]],
    canon: Mapping[tuple[str, str], str],
) -> dict[str, int]:
    """Owned-asset counts, summed onto the canonical id each face belongs to."""
    result: dict[str, int] = {}
    for account, counts in per_account.items():
        for person_id, count in counts.items():
            canonical_id = canon.get((account, person_id), person_id)
            result[canonical_id] = result.get(canonical_id, 0) + count
    return result


def sum_month_counts(per_account: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    """Every account's month-to-asset-count buckets, summed onto one calendar."""
    result: dict[str, int] = {}
    for counts in per_account.values():
        for month, count in counts.items():
            result[month] = result.get(month, 0) + count
    return result


def store_birth_dates(document: Mapping[str, Any]) -> dict[str, date]:
    """Every store person's own id to their confirmed birth date, when they have one.

    The registry's `birth_date` is the one the owner or the scan filled in; reading it
    needs no account, unlike an Immich roster's per-account `birthDate`.
    """
    result: dict[str, date] = {}
    for entry in people_entries(dict(document)):
        raw = entry.get("birth_date")
        if not raw:
            continue
        ids = entry_ids(entry)
        if not ids:
            continue
        try:
            result[ids[0]] = date.fromisoformat(str(raw))
        except ValueError:
            continue
    return result


def overlay_birth_dates(
    people: Sequence[MergedPerson], store_dates: Mapping[str, date]
) -> list[MergedPerson]:
    """The store's birth date wins; a roster's `birthDate` only fills what the store lacks."""
    return [
        person if person.id not in store_dates else _with_birth_date(person, store_dates)
        for person in people
    ]


def _with_birth_date(person: MergedPerson, store_dates: Mapping[str, date]) -> MergedPerson:
    return MergedPerson(person.id, person.name, store_dates[person.id], person.thumbnail_path)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
