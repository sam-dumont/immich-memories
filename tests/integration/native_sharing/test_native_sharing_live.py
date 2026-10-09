"""Native sharing on the disposable library seeded by the retained research probe."""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from immich_memories.analysis.household_source import HouseholdWindows
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.person_expression import PersonExpression
from immich_memories.api.person_scope import people_in_window
from immich_memories.cli.run_people import resolve_run_people
from immich_memories.config_models import ImmichConfig
from immich_memories.db import Store, StoreLocation, close_stores, open_store
from immich_memories.people.transfer import import_document
from immich_memories.timeperiod import DateRange


@dataclass
class Household:
    # A failing test must never print disposable API keys in its fixture repr.
    state: dict = field(repr=False)
    store: Store = field(repr=False)
    client: AccessBoundClient = field(repr=False)

    def __iter__(self) -> Iterator[Any]:
        return iter((self.state, self.store, self.client))


@pytest.fixture
def sharing_store(tmp_path):
    from tests.store.backends import drop_schema

    url = os.environ.get("IMMICH_SHARING_DATABASE_URL")
    schema = f"sharing_{uuid4().hex[:12]}"
    location = (
        StoreLocation(url=url, schema=schema)
        if url
        else StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    )
    try:
        yield open_store(location=location)
    finally:
        close_stores()
        if url:
            drop_schema(url, schema)


@pytest.fixture
def household(sharing_store):
    path = os.environ.get("IMMICH_SHARING_STATE")
    if not path:
        pytest.skip("Set IMMICH_SHARING_STATE to the disposable sharing probe state")
    state = json.loads(Path(path).read_text())
    url = state.get("url", "http://127.0.0.1:2303")
    config = ImmichConfig(
        url=url,
        api_key=state["keys"]["primary"],
        native_sharing=True,
        accounts={"partner": {"url": url, "api_key": state["keys"]["partner"]}},
    )
    store = sharing_store
    import_document(
        store,
        {
            "version": 1,
            "people": [
                {
                    "ids": [state["person"]],
                    "name": "Shared Child",
                    "confirmed": {"notes": "Preserve this answer"},
                }
            ],
        },
    )
    with AccessBoundClient(config) as client:
        yield Household(state, store, client)


def _verify_person_filter(household, tmp_path):
    state, store, client = household
    resolved = resolve_run_people(
        client,
        expression=PersonExpression("person", value=state["person"]),
        person_names=[],
        person_match="and",
        accounts=("primary", "partner"),
        store=store,
    )
    window = DateRange(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC)
    )
    videos, photos = people_in_window(
        HouseholdWindows(client, ("primary", "partner")),
        window,
        resolved.condition,
        face_accounts=resolved.face_accounts,
    )
    selected = {asset.id for asset in [*videos, *photos]}
    assert state["target"] in selected
    # Only the target has a face; nearby pictures must not widen a people filter.
    assert selected == {state["target"]}
    assert state["outside_asset"] not in selected
    assert client.download_asset(state["target"], tmp_path / "target.jpg").stat().st_size > 0


def test_shared_person_keeps_only_pictures_with_that_face(household, tmp_path):
    _verify_person_filter(household, tmp_path)


def test_partner_only_run_uses_the_existing_primary_binding(household, tmp_path):
    state, store, client = household
    resolved = resolve_run_people(
        client,
        expression=PersonExpression("person", value=state["person"]),
        person_names=[],
        person_match="and",
        accounts=("partner",),
        store=store,
    )
    window = DateRange(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC)
    )
    videos, photos = people_in_window(
        HouseholdWindows(client, ("partner",)),
        window,
        resolved.condition,
        face_accounts=resolved.face_accounts,
    )
    selected = {asset.id for asset in [*videos, *photos]}
    assert state["target"] in selected
    assert selected <= set(state["partner_assets"])
    assert client.download_asset(state["target"], tmp_path / "partner-only.jpg").stat().st_size > 0


def test_owner_reads_preserve_duplicates_favourites_and_scope_with_timeline_off(household):
    from tests.integration.immich_gate.seed import Seeder

    from immich_memories.analysis.exact_copies import fold_exact_copies

    state, _, client = household
    url = state.get("url", "http://127.0.0.1:2303")
    a, b = (Seeder(url, state["keys"][name]) for name in ("primary", "partner"))
    primary, partner = (state["users"][name]["id"] for name in ("primary", "partner"))
    outgoing = {
        user["id"] for user in b.call("GET", "/partners", params={"direction": "shared-by"})
    }
    added = primary not in outgoing
    if added:
        b.call("POST", "/partners", json={"sharedWithId": primary})
    window = DateRange(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC)
    )
    try:
        pools = []
        for enabled in (True, False):
            a.call("PUT", f"/partners/{partner}", json={"inTimeline": enabled})
            source = HouseholdWindows(client, ("primary", "partner"))
            assets = [
                *source.get_photos_for_date_range(window),
                *source.get_videos_for_date_range(window),
            ]
            assert len(assets) == 134
            assert state["outside_asset"] not in {asset.id for asset in assets}
            duplicate = next(asset for asset in assets if asset.id == state["duplicate"])
            assert duplicate.is_favorite
            folded = fold_exact_copies(assets, primary_owner_id=primary)
            assert len(folded.pool) == 133
            assert next(
                asset for asset in folded.pool if asset.checksum == duplicate.checksum
            ).is_favorite
            pools.append({asset.id for asset in folded.pool})
        assert pools[0] == pools[1]
    finally:
        a.call("PUT", f"/partners/{partner}", json={"inTimeline": True})
        if added:
            b.call("DELETE", f"/partners/{primary}")
        a.http.close()
        b.http.close()


def test_people_role_downgrade_and_revocation_are_checked_each_run(household):
    from tests.integration.immich_gate.seed import Seeder

    state, store, client = household
    if client.get_server_info().minor != 3:
        pytest.skip("Explicit people grants begin in 3.3")
    a = Seeder(state.get("url", "http://127.0.0.1:2303"), state["keys"]["primary"])
    person, partner = state["person"], state["users"]["partner"]["id"]

    def resolve():
        return resolve_run_people(
            client,
            expression=PersonExpression("person", value=person),
            person_names=[],
            person_match="and",
            accounts=("primary", "partner"),
            store=store,
        )

    try:
        for role in ("admin", "write", "read"):
            a.call(
                "PUT",
                "/people/users",
                json={"personIds": [person], "sharedWithIds": [partner], "role": role},
            )
            assert resolve().face_accounts[person] == frozenset({"primary", "partner"})
        a.call("DELETE", "/people/users", json=[{"personId": person, "sharedWithId": partner}])
        # Revocation removes shared metadata, but this recipient owns a recognition
        # record for the same group. Owner reads must still find the tagged picture.
        assert resolve().face_accounts[person] == frozenset({"primary", "partner"})
        assert a.call("GET", "/people/users", params={"personId": person}) == []
        _verify_person_filter(household, Path(os.environ["IMMICH_SHARING_STATE"]).parent)
    finally:
        a.call(
            "PUT",
            "/people/users",
            json={"personIds": [person], "sharedWithIds": [partner], "role": "read"},
        )
        a.http.close()


def test_native_discovery_and_owner_download_need_only_documented_read_permissions(
    household, tmp_path
):
    import httpx
    from tests.integration.immich_gate.seed import ADMIN_PASSWORD, _checked

    from immich_memories.api.permissions import READ_PERMISSIONS

    state, store, _ = household
    url = state.get("url", "http://127.0.0.1:2303")
    created = []
    keys = {}
    try:
        for name in ("primary", "partner"):
            login = _checked(
                httpx.post(
                    f"{url}/api/auth/login",
                    json={"email": state["users"][name]["email"], "password": ADMIN_PASSWORD},
                )
            )
            session = httpx.Client(
                base_url=f"{url}/api", headers={"Authorization": f"Bearer {login['accessToken']}"}
            )
            key = _checked(
                session.post(
                    "/api-keys",
                    json={"name": "native-read-gate", "permissions": list(READ_PERMISSIONS)},
                )
            )
            created.append((session, key["apiKey"]["id"]))
            keys[name] = key["secret"]
        config = ImmichConfig(
            url=url,
            api_key=keys["primary"],
            native_sharing=True,
            accounts={"partner": {"url": url, "api_key": keys["partner"]}},
        )
        with AccessBoundClient(config) as client:
            _verify_person_filter(Household(state, store, client), tmp_path)
            assert client.get_asset_thumbnail(state["target"])
            assert client.get_asset_faces(state["target"])
    finally:
        for session, key_id in created:
            _checked(session.delete(f"/api-keys/{key_id}"))
            session.close()


def test_upstream_merge_never_rewrites_a_saved_local_identity(household):
    from tests.integration.immich_gate.seed import Seeder

    from immich_memories.api.accounts import AccountUnavailable
    from immich_memories.people.companion import load_document

    state, store, client = household
    a = Seeder(state.get("url", "http://127.0.0.1:2303"), state["keys"]["primary"])
    try:
        old = a.call("POST", "/people", json={"name": "Merge source"})["id"]
        import_document(
            store,
            {
                "version": 1,
                "people": [
                    {
                        "ids": [old],
                        "name": "Local identity",
                        "confirmed": {"notes": "Keep this decision"},
                    }
                ],
            },
            replace=True,
        )
        before = load_document(store)
        a.call("POST", "/people/merge", json={"ids": [state["person"], old]})
        with pytest.raises(AccountUnavailable, match="person|identity"):
            resolve_run_people(
                client,
                expression=PersonExpression("person", value=old),
                person_names=[],
                person_match="and",
                accounts=("primary", "partner"),
                store=store,
            )
        assert load_document(store) == before
    finally:
        a.http.close()


def test_shared_person_stays_one_registry_identity_and_cross_account_link(household):
    from immich_memories.analysis.person_resolution import store_people
    from immich_memories.automation.people_merge import canonical_person_map, merge_people
    from immich_memories.config_loader import Config
    from immich_memories.people.companion import load_document, people_entries
    from immich_memories.web.people_accounts import account_people, account_reads

    state, store, client = household
    before = load_document(store)
    opened = client.open_accounts(("primary", "partner"))
    rosters = {name: account.client.get_all_people() for name, account in opened.items()}
    merged = merge_people(rosters, canonical_person_map(store_people(before)))
    assert [person.id for person in merged] == [state["person"]]
    config = Config(
        immich=ImmichConfig(
            url=state["url"],
            api_key=state["keys"]["primary"],
            native_sharing=True,
            accounts={"partner": {"url": state["url"], "api_key": state["keys"]["partner"]}},
        )
    )
    linked = account_people("partner", store, config, account_reads(config))
    assert len(linked) == 1
    assert linked[0].linked_to == state["person"]
    assert linked[0].suggested is False
    assert len(people_entries(load_document(store))) == 1
    assert load_document(store) == before


def test_shared_person_counts_each_owned_picture_once(household):
    from immich_memories.analysis.person_resolution import store_people
    from immich_memories.automation.people_merge import canonical_person_map, merge_counts
    from immich_memories.people.companion import load_document

    state, store, client = household
    opened = client.open_accounts(("primary", "partner"))
    counts = {
        name: {
            state["person"]: account.client.count_assets_with_people(
                [state["person"]], owner_id=account.user.id
            )
        }
        for name, account in opened.items()
    }
    merged = merge_counts(counts, canonical_person_map(store_people(load_document(store))))
    assert merged == {state["person"]: 1}


def test_native_automation_uses_owned_counts(household):
    from datetime import date

    from immich_memories.automation.candidate_discovery import CandidateDiscovery
    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.config_loader import Config
    from immich_memories.tracking import RunDatabase

    state, store, _ = household
    import_document(
        store,
        {
            "version": 1,
            "people": [
                {
                    "ids": ["manual:shared", state["person"]],
                    "name": "Shared Child",
                    "confirmed": {"notes": "Preserve this answer"},
                }
            ],
        },
        replace=True,
    )
    config = Config(
        immich=ImmichConfig(
            url=state["url"],
            api_key=state["keys"]["primary"],
            native_sharing=True,
            accounts={"partner": {"url": state["url"], "api_key": state["keys"]["partner"]}},
        )
    )
    config.automation.accounts = ["primary", "partner"]
    config.automation.detect_trips = False
    config.automation.detect_holidays = False
    discovery = CandidateDiscovery(config, RunDatabase(store), AutomationStateStore(store))
    snapshot = discovery._library_snapshot(config.automation, date(2025, 1, 20), store)
    assert snapshot.spotlight_counts == {"manual:shared": 1}
    assert [person.id for person in snapshot.people] == ["manual:shared"]


def test_mobile_edit_stack_plays_the_edit_instead_of_the_original(household):
    from tests.integration.immich_gate.seed import Seeder

    from immich_memories.analysis.stacks import fold_stacks
    from immich_memories.api.stack_discovery import discover_stack_map

    state, _, client = household
    api = Seeder(state["url"], state["keys"]["primary"])
    window = DateRange(datetime(2024, 6, 1), datetime(2024, 6, 30, 23, 59, 59))
    original, edit = [
        asset.id
        for asset in client.get_photos_for_date_range(window)
        if asset.owner_id == state["users"]["primary"]["id"]
    ][:2]
    stack = api.call("POST", "/stacks", json={"assetIds": [edit, original]})
    try:
        assert stack["primaryAssetId"] == edit
        mapping = discover_stack_map(client.open_accounts(("primary", "partner")))
        assert mapping[original] == edit
        folded = fold_stacks([client.get_asset(original), client.get_asset(edit)], mapping)
        assert folded[original].id == edit
    finally:
        api.call("DELETE", f"/stacks/{stack['id']}")
        api.http.close()


def test_normalized_multilingual_ocr_reaches_the_personal_document_gate(household):
    from tests.integration.native_sharing.ocr_fixture import OCR_TEXT

    from immich_memories.analysis.editorial_carrier_eligibility import personal_document
    from immich_memories.analysis.editorial_document_ocr import document_ocr_port

    state, _, client = household
    reader = document_ocr_port(client, accounts=("primary", "partner"))
    assert reader is not None
    text = reader(state["target"], True)
    assert text == OCR_TEXT
    assert personal_document("", {"frame_kind": "screen_or_document"}, ocr_text=text)
