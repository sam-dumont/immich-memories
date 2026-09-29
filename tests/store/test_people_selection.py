"""`--person` and `--people-expression` resolve through the people store (#1500 slice 7).

A person the store holds is every face id bound to them, each read only in its own
account's pictures. Anybody else is matched on the Immich roster, as before the store.
The Immich server is the two-account fake of `tests/household_fake.py`; the store is real.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from immich_memories.analysis.editorial_source import resolve_named_expression
from immich_memories.analysis.household_source import HouseholdWindows
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.person_expression import PersonExpression
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.cli._asset_fetch import fetch_media
from immich_memories.cli._live_display import QuietDisplay
from immich_memories.cli.run_people import resolve_run_people
from immich_memories.config_models import ImmichConfig
from immich_memories.people.transfer import import_document
from immich_memories.timeperiod import DateRange
from tests.household_fake import (
    PARTNER_KEY,
    PRIMARY_KEY,
    URL,
    FakeHousehold,
    immich_config,
    picture,
)

WINDOW = DateRange(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 30, 23, 59, tzinfo=UTC))
HOUSEHOLD = ("primary", "partner")


def _person(ids: list[str], name: str, accounts: dict[str, str] | None = None) -> dict:
    return {
        "ids": ids,
        **({"accounts": accounts} if accounts else {}),
        "name": name,
        "birth_date": None,
        "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {}, "links": []},
        "confirmed": {"role": None, "links": [], "notes": None},
    }


# Alex is one person with a face cluster in each account; Kit is bound in the partner's alone.
REGISTRY = {
    "version": 1,
    "people": [
        _person(["alex-p", "alex-q"], "Alex", {"alex-q": "partner"}),
        _person(["kit-q"], "Kit", {"kit-q": "partner"}),
    ],
}


@pytest.fixture
def immich(monkeypatch) -> FakeHousehold:
    server = FakeHousehold(
        library={
            PRIMARY_KEY: [
                picture("p-park", "primary", 2, ("alex-p",)),
                # The partner's alias on a picture the primary owns: never Alex's evidence.
                picture("p-odd", "primary", 6, ("alex-q",)),
                picture("p-party", "primary", 7, ("alex-p",)),
                picture("p-solo", "primary", 8, ("alex-p",)),
                picture("p-robin", "primary", 9, ("robin-p",)),
            ],
            PARTNER_KEY: [
                picture("q-lake", "partner", 5, ("alex-q",)),
                # Ten minutes after p-party: the same afternoon, another phone.
                picture("q-party", "partner", 7, ("kit-q",), minute=10),
            ],
        },
        roster={
            PRIMARY_KEY: [{"id": "alex-p", "name": "Alex"}, {"id": "robin-p", "name": "Robin"}],
            PARTNER_KEY: [{"id": "alex-q", "name": "Alex"}],
        },
    )
    return server.install(monkeypatch)


def _discover(store, accounts=(), *, names=(), expression=None, match="and"):
    with AccessBoundClient(ImmichConfig(**immich_config())) as client:
        people = resolve_run_people(
            client,
            expression=PersonExpression.parse(expression) if expression else None,
            person_names=list(names),
            person_match=match,
            accounts=accounts,
            store=store,
        )
        _videos, photos = fetch_media(
            client=HouseholdWindows(client, accounts) if accounts else client,
            progress=QuietDisplay(),
            date_ranges=[WINDOW],
            person_ids=people.person_ids,
            person_match=match,
            person_expression=people.condition,
            face_accounts=people.face_accounts,
        )
    return people, {photo.id for photo in photos}


def test_a_store_person_is_found_in_both_accounts_pictures(store, immich):
    import_document(store, REGISTRY)

    _, found = _discover(store, HOUSEHOLD, names=["Alex"])

    # q-lake through the partner's alias; q-party because Alex is in the party's episode.
    assert found == {"p-park", "p-party", "p-solo", "q-lake", "q-party"}


def test_an_alias_only_matches_its_own_accounts_pictures(store, immich):
    import_document(store, REGISTRY)

    _, household = _discover(store, HOUSEHOLD, expression='"Alex"')
    people, primary_only = _discover(store, names=["Alex"])

    assert "p-odd" not in household
    # A one-account run reads the primary's aliases alone, as a flat id like always.
    assert people.person_ids == ["alex-p"]
    assert primary_only == {"p-park", "p-party", "p-solo"}


def test_a_person_the_store_does_not_hold_falls_back_to_the_roster(store, immich):
    import_document(store, REGISTRY)

    assert _discover(store, names=["Robin"])[1] == {"p-robin"}
    assert _discover(store, HOUSEHOLD, expression='"Robin"')[1] == {"p-robin"}


@pytest.mark.parametrize(
    "registry", [None, {"version": 1, "people": [_person(["alex-p"], "Alex")]}]
)
def test_a_one_account_run_matches_as_it_did_before_the_store(store, immich, registry):
    if registry:
        import_document(store, registry)
    with SyncImmichClient(base_url=URL, api_key=PRIMARY_KEY, api_version="v2") as client:
        before_ids = [client.get_person_by_name("alex").id]
        before_condition = resolve_named_expression(
            PersonExpression.parse('"Alex" OR "Robin"'), client.get_all_people(with_hidden=True)
        )
        _, before = fetch_media(
            client=client, progress=QuietDisplay(), date_ranges=[WINDOW], person_ids=before_ids
        )

    people, found = _discover(store, names=["alex"])
    grouped, _ = _discover(store, expression='"Alex" OR "Robin"')

    assert (people.person_ids, people.condition, dict(people.face_accounts)) == (
        before_ids,
        None,
        {},
    )
    assert found == {photo.id for photo in before}
    assert grouped.condition == before_condition


def test_an_and_holds_per_episode_across_both_accounts_copies(store, immich):
    import_document(store, REGISTRY)

    _, found = _discover(store, HOUSEHOLD, expression='"Alex" AND "Kit"')

    # Alex is on the primary's picture of the party and Kit on the partner's: one episode.
    assert found == {"p-party", "q-party"}


def test_a_person_bound_only_in_an_account_the_run_does_not_read_is_refused(store, immich):
    import_document(store, REGISTRY)

    with pytest.raises(ValueError, match="no face in the accounts this run reads"):
        _discover(store, expression='"Kit"')
    assert not any(path.endswith("/search/metadata") for path in immich.requests)
