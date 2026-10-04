"""Native identity discovery through the real clients and people store."""

import pytest

from immich_memories.analysis.household_source import HouseholdWindows
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.person_scope import people_in_window, window_condition
from immich_memories.cli.run_people import resolve_run_people
from immich_memories.config_models import ImmichConfig
from immich_memories.people.transfer import import_document
from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture
from tests.store.test_people_selection import HOUSEHOLD, WINDOW, _person


def test_native_cluster_identity_finds_the_partner_picture_without_a_second_binding(
    store, monkeypatch
):
    server = FakeHousehold(
        library={
            PARTNER_KEY: [
                picture(f"q-{i}", "partner", 2, ("shared",) if i == 0 else (), minute=i)
                for i in range(4)
            ]
        },
        roster={PRIMARY_KEY: [{"id": "shared", "name": "Alex"}], PARTNER_KEY: []},
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
    ).install(monkeypatch)
    import_document(store, {"version": 1, "people": [_person(["shared"], "Alex")]})
    config = ImmichConfig(**immich_config(), native_sharing=True)
    with AccessBoundClient(config) as client:
        people = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=HOUSEHOLD,
            store=store,
        )
        condition = window_condition(people.person_ids, person_expression=people.condition)
        _, photos = people_in_window(
            HouseholdWindows(client, HOUSEHOLD),
            WINDOW,
            condition,
            face_accounts=people.face_accounts,
        )
    # Strict per picture: only the partner frame that shows the face, not its whole outing.
    assert {photo.id for photo in photos} == {"q-0"}
    assert not any(path.endswith("/people/users") for path in server.requests)


def test_experimental_33_discovers_people_access_before_using_shared_roster(store, monkeypatch):
    server = FakeHousehold(
        roster={
            PRIMARY_KEY: [{"id": "shared", "name": "Alex"}],
            PARTNER_KEY: [{"id": "shared", "name": "Alex"}],
        },
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
        shares=[
            {
                "personId": "shared",
                "sharedById": "user-primary",
                "sharedWithId": "user-partner",
                "role": "read",
            }
        ],
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        people = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=HOUSEHOLD,
            store=store,
        )
    assert people.face_accounts["shared"] == frozenset(HOUSEHOLD)
    assert server.requests.count("/api/people/users") == 2


def test_revoked_shared_person_cannot_silently_drop_the_partner_episode(store, monkeypatch):
    import pytest

    from immich_memories.api.accounts import AccountUnavailable

    FakeHousehold(
        roster={PRIMARY_KEY: [{"id": "shared", "name": "Alex"}], PARTNER_KEY: []},
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
    ).install(monkeypatch)
    import_document(store, {"version": 1, "people": [_person(["shared"], "Alex")]})
    with (
        AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client,
        pytest.raises(AccountUnavailable, match="people access"),
    ):
        resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=HOUSEHOLD,
            store=store,
        )


def test_native_primary_only_discovery_keeps_owner_scope(store, monkeypatch):
    from immich_memories.cli.run_people import run_client, run_windows

    FakeHousehold(
        roster={PRIMARY_KEY: [{"id": "shared", "name": "Alex"}]},
        library={
            PRIMARY_KEY: [
                picture("own", "primary", 2, ("shared",)),
                picture("unselected", "partner", 3, ("shared",)),
            ]
        },
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "cluster"},
    ).install(monkeypatch)
    with run_client(ImmichConfig(**immich_config(), native_sharing=True), ()) as client:
        people = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=(),
            store=store,
        )
        _, photos = people_in_window(
            run_windows(client, ()),
            WINDOW,
            window_condition(people.person_ids),
            face_accounts=people.face_accounts,
        )
    assert {photo.id for photo in photos} == {"own"}


def test_both_accounts_face_evidence_survives_a_repeated_asset_read(store, monkeypatch):
    from immich_memories.api.person_expression import PersonExpression

    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("shared-photo", "partner", 2, ("alex",))],
            PARTNER_KEY: [picture("shared-photo", "partner", 2, ("kit",))],
        }
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config())) as client:
        _, photos = people_in_window(
            HouseholdWindows(client, HOUSEHOLD), WINDOW, PersonExpression.parse('"alex" AND "kit"')
        )
    assert {photo.id for photo in photos} == {"shared-photo"}


def test_empty_roster_is_verified_by_id_and_confirmations_round_trip(store, monkeypatch):
    from immich_memories.api.person_expression import PersonExpression
    from immich_memories.people.companion import load_document
    from immich_memories.people.transfer import export_yaml, parse_yaml

    FakeHousehold(
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
        direct_people={
            PRIMARY_KEY: [{"id": "shared", "name": "Alex"}],
            PARTNER_KEY: [{"id": "shared", "name": "Alex"}],
        },
    ).install(monkeypatch)
    person = _person(["shared"], "Alex")
    person["confirmed"]["notes"] = "Keep my decision"
    document = {
        "version": 1,
        "people": [person],
        "groups": [
            {"label": "Family", "expression": PersonExpression("person", value="shared").to_dict()}
        ],
    }
    import_document(store, document)
    before = load_document(store)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        resolved = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=HOUSEHOLD,
            store=store,
        )
    assert resolved.face_accounts["shared"] == frozenset(HOUSEHOLD)
    import_document(store, parse_yaml(export_yaml(store)), replace=True)
    assert load_document(store) == before


def test_enabled_legacy_single_account_keeps_the_existing_window_path(store, monkeypatch):
    from immich_memories.cli.run_people import run_client, run_windows

    FakeHousehold(
        roster={PRIMARY_KEY: [{"id": "face", "name": "Alex"}]},
        library={PRIMARY_KEY: [picture("shared", "partner", 2, ("face",))]},
    ).install(monkeypatch)
    with run_client(ImmichConfig(**immich_config(), native_sharing=True), ()) as client:
        resolved = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=(),
            store=store,
        )
        _, photos = people_in_window(
            run_windows(client, ()),
            WINDOW,
            window_condition(resolved.person_ids),
            face_accounts=resolved.face_accounts,
        )
    assert {photo.id for photo in photos} == {"shared"}


def test_native_name_fallback_keeps_case_insensitive_person_option(store, monkeypatch):
    FakeHousehold(
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "cluster"},
        roster={PRIMARY_KEY: [{"id": "face", "name": "Alex"}]},
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        result = resolve_run_people(
            client,
            expression=None,
            person_names=["alex"],
            person_match="and",
            accounts=("primary",),
            store=store,
        )
    assert result.person_ids == ["face"]


def test_shared_roster_uses_a_named_record_when_the_primary_record_is_unnamed(store, monkeypatch):
    FakeHousehold(
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
        roster={
            PRIMARY_KEY: [{"id": "shared", "name": ""}],
            PARTNER_KEY: [{"id": "shared", "name": "Alex"}],
        },
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        result = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=HOUSEHOLD,
            store=store,
        )
    assert result.person_ids == ["shared"]


def test_owner_ids_on_another_server_do_not_admit_an_unselected_library(store, monkeypatch):
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("outside-collision", "partner", 2, ())],
            PARTNER_KEY: [picture("selected", "partner", 2, ())],
        }
    ).install(monkeypatch)
    config = immich_config()
    config["accounts"]["partner"]["url"] = "https://second.example.test"
    with AccessBoundClient(ImmichConfig(**config)) as client:
        photos = HouseholdWindows(client, HOUSEHOLD).get_photos_for_date_range(WINDOW)
    assert {photo.id for photo in photos} == {"selected"}


def test_live_photo_companion_ids_cannot_cross_server_routes(monkeypatch):
    import pytest

    from immich_memories.api.accounts import AccountUnavailable

    own = picture("own", "primary", 2, ()) | {"livePhotoVideoId": "motion"}
    partner = picture("partner", "partner", 2, ()) | {"livePhotoVideoId": "motion"}
    FakeHousehold(library={PRIMARY_KEY: [own], PARTNER_KEY: [partner]}).install(monkeypatch)
    config = immich_config()
    config["accounts"]["partner"]["url"] = "https://second.example.test"
    with (
        AccessBoundClient(ImmichConfig(**config)) as client,
        pytest.raises(AccountUnavailable, match="same asset ID"),
    ):
        HouseholdWindows(client, HOUSEHOLD).get_photos_for_date_range(WINDOW)


@pytest.mark.parametrize("minor", [2, 3])
@pytest.mark.parametrize("visible", [True, False])
def test_partner_only_run_uses_a_native_identity_bound_to_primary(
    store, monkeypatch, minor, visible
):
    server = FakeHousehold(
        library={PARTNER_KEY: [picture("partner-photo", "partner", 2, ("shared",))]},
        roster={PARTNER_KEY: [{"id": "shared", "name": "Alex"}] if visible else []},
        direct_people={PARTNER_KEY: [{"id": "shared", "name": "Alex"}]},
        version={"major": 3, "minor": minor, "patch": 0, "prerelease": 1 if minor == 3 else 0},
        clusters={PARTNER_KEY: "cluster"},
    ).install(monkeypatch)
    import_document(store, {"version": 1, "people": [_person(["shared"], "Alex")]})
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        result = resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=("partner",),
            store=store,
        )
        _, photos = people_in_window(
            HouseholdWindows(client, ("partner",)),
            WINDOW,
            window_condition(result.person_ids),
            face_accounts=result.face_accounts,
        )
    assert {photo.id for photo in photos} == {"partner-photo"}
    assert {user for user, _ in server.reads} == {"user-partner"}


@pytest.mark.parametrize(
    "minor,partner_url", [(1, "https://immich.example.test"), (2, "https://other.example.test")]
)
def test_unselected_binding_needs_native_identity_on_the_same_server(
    store, monkeypatch, minor, partner_url
):
    FakeHousehold(
        roster={PARTNER_KEY: [{"id": "shared", "name": "Alex"}]},
        version={"major": 3, "minor": minor, "patch": 0},
        clusters={PARTNER_KEY: "cluster"},
    ).install(monkeypatch)
    import_document(store, {"version": 1, "people": [_person(["shared"], "Alex")]})
    config = immich_config()
    config["accounts"]["partner"]["url"] = partner_url
    with (
        AccessBoundClient(ImmichConfig(**config, native_sharing=True)) as client,
        pytest.raises(ValueError, match="no face in the accounts"),
    ):
        resolve_run_people(
            client,
            expression=None,
            person_names=["Alex"],
            person_match="and",
            accounts=("partner",),
            store=store,
        )
