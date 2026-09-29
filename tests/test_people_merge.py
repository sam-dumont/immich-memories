"""Discovery's cross-account merge: same-person folding, counts and birth dates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from immich_memories.analysis.person_resolution import PersonAlias, StorePerson
from immich_memories.automation.people_merge import (
    canonical_person_map,
    merge_counts,
    merge_people,
    overlay_birth_dates,
    store_birth_dates,
    sum_month_counts,
)


@dataclass
class _Person:
    id: str
    name: str = ""
    birth_date: object = None
    thumbnail_path: str | None = None


def _store_person(person_id: str, name: str, *aliases: tuple[str, str]) -> StorePerson:
    return StorePerson(
        person_id, name, tuple(PersonAlias(face, account) for face, account in aliases)
    )


def test_a_person_bound_in_two_accounts_folds_to_one_canonical_row():
    store = [
        _store_person("kid-a", "Kid A", ("primary-face", "primary"), ("partner-face", "partner"))
    ]
    canon = canonical_person_map(store)
    per_account = {
        "primary": [_Person("primary-face", "Kid A", thumbnail_path="/t.jpg")],
        "partner": [_Person("partner-face", "Kid A")],
    }

    merged = merge_people(per_account, canon)

    assert len(merged) == 1
    assert merged[0].id == "kid-a"
    assert merged[0].thumbnail_path == "/t.jpg"


def test_an_unbound_face_keeps_its_own_account_id():
    per_account = {"partner": [_Person("stranger-face", "Stranger")]}

    merged = merge_people(per_account, canon={})

    assert merged == [
        type(merged[0])(id="stranger-face", name="Stranger", birth_date=None, thumbnail_path=None)
    ]


def test_a_later_accounts_fields_only_fill_what_the_first_left_empty():
    canon = {("primary", "p1"): "canon-1", ("partner", "p2"): "canon-1"}
    per_account = {
        "primary": [_Person("p1", name="", thumbnail_path=None)],
        "partner": [_Person("p2", name="Kid A", thumbnail_path="/partner.jpg")],
    }

    merged = merge_people(per_account, canon)

    assert merged == [
        type(merged[0])(id="canon-1", name="Kid A", birth_date=None, thumbnail_path="/partner.jpg")
    ]


def test_an_immich_roster_birth_datetime_is_normalized_to_a_date():
    per_account = {"primary": [_Person("p1", "Kid A", birth_date=datetime(2018, 4, 2, 9, 30))]}

    merged = merge_people(per_account, canon={})

    assert merged[0].birth_date == date(2018, 4, 2)


def test_merge_counts_sums_onto_the_canonical_id():
    canon = {("primary", "p1"): "canon-1", ("partner", "p2"): "canon-1"}
    per_account = {"primary": {"p1": 30}, "partner": {"p2": 12}}

    assert merge_counts(per_account, canon) == {"canon-1": 42}


def test_sum_month_counts_adds_every_accounts_calendar():
    per_account = {"primary": {"2026-01": 5, "2026-02": 3}, "partner": {"2026-01": 2}}

    assert sum_month_counts(per_account) == {"2026-01": 7, "2026-02": 3}


def test_store_birth_dates_reads_the_registrys_own_field():
    document = {
        "people": [
            {"ids": ["kid-a"], "name": "Kid A", "birth_date": "2018-04-02"},
            {"ids": ["kid-b"], "name": "Kid B", "birth_date": None},
        ]
    }

    assert store_birth_dates(document) == {"kid-a": date(2018, 4, 2)}


def test_store_birth_date_wins_over_the_immich_roster():
    people = [_MergedPersonLike("kid-a", "Kid A", datetime(2018, 1, 1), None)]
    store_dates = {"kid-a": date(2018, 4, 2)}

    overlaid = overlay_birth_dates(people, store_dates)

    assert overlaid[0].birth_date == date(2018, 4, 2)


def test_a_roster_birth_date_survives_when_the_store_has_none():
    from immich_memories.automation.people_merge import MergedPerson

    people = [MergedPerson("kid-a", "Kid A", date(2018, 1, 1), None)]

    overlaid = overlay_birth_dates(people, {})

    assert overlaid[0].birth_date == date(2018, 1, 1)


def _MergedPersonLike(person_id, name, birth_date, thumbnail):
    from immich_memories.automation.people_merge import MergedPerson

    normalized = birth_date.date() if isinstance(birth_date, datetime) else birth_date
    return MergedPerson(person_id, name, normalized, thumbnail)
