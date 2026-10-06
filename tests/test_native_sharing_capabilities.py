"""Actual server versions control discovery, independently of the configured API major."""

import pytest

from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.accounts import AccountUnavailable
from immich_memories.api.compatibility import UnsupportedImmichVersion
from immich_memories.api.models import ServerInfo
from immich_memories.api.native_sharing import native_mode
from immich_memories.config_models import ImmichConfig
from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config


@pytest.mark.parametrize(
    ("prerelease", "expected"),
    [
        (0, None),  # rc.0: not validated, refused
        (1, "people"),  # rc.1: validated
        (2, "people"),  # rc.2: immich-app/immich#31620 people-sharing server code is unchanged
        (3, "people"),  # a later rc, same server code
        (None, "people"),  # the final 3.3.0 release
    ],
)
def test_native_mode_accepts_rc1_and_later_but_not_rc0(prerelease, expected):
    version = ServerInfo(major=3, minor=3, patch=0, prerelease=prerelease)
    if expected is None:
        with pytest.raises(UnsupportedImmichVersion):
            native_mode(version)
    else:
        assert native_mode(version) == expected


@pytest.mark.parametrize("minor", [0, 1, 2, 3, 9])
def test_disabled_native_mode_never_discovers_newer_apis(monkeypatch, minor):
    server = FakeHousehold(version={"major": 3, "minor": minor, "patch": 0}).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config())) as client:
        assert client.native_people(("primary", "partner")) is None
    assert server.requests == []


@pytest.mark.parametrize("major,minor", [(2, 7), (3, 0), (3, 1)])
def test_pre32_keeps_bindings_with_a_clear_explanation(monkeypatch, caplog, major, minor):
    server = FakeHousehold(version={"major": major, "minor": minor, "patch": 1}).install(
        monkeypatch
    )
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        assert client.native_people(("primary", "partner")) is None
    assert "Keeping existing bindings" in caplog.text
    assert not any("/people" in path for path in server.requests)


@pytest.mark.parametrize(
    "version",
    [
        {"major": 4, "minor": 0, "patch": 0},
        {"major": 3, "minor": 4, "patch": 0},
        {"major": 3, "minor": 3, "patch": 0, "prerelease": 0},
        {"major": 3, "minor": 2, "patch": 5, "prerelease": 1},
    ],
)
def test_major_override_cannot_invent_native_capabilities(monkeypatch, version):
    server = FakeHousehold(version=version).install(monkeypatch)
    with (
        AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client,
        pytest.raises(UnsupportedImmichVersion),
    ):
        client.native_people(("primary", "partner"))
    assert not any("/people" in path for path in server.requests)


def test_cluster_membership_changes_are_not_silent_scope_changes(monkeypatch):
    server = FakeHousehold(
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "first", PARTNER_KEY: "first"},
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        client.native_people(("primary", "partner"))
        server.clusters[PARTNER_KEY] = "different"
        with pytest.raises(AccountUnavailable, match="cluster group"):
            client.native_people(("primary", "partner"))


def test_ids_are_not_shared_between_servers(monkeypatch):
    FakeHousehold(
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "same-string", PARTNER_KEY: "same-string"},
        roster={
            PRIMARY_KEY: [{"id": "shared", "name": "Alex"}],
            PARTNER_KEY: [{"id": "shared", "name": "Alex"}],
        },
    ).install(monkeypatch)
    config = immich_config()
    config["accounts"]["partner"]["url"] = "https://other.example.test"
    with (
        AccessBoundClient(ImmichConfig(**config, native_sharing=True)) as client,
        pytest.raises(AccountUnavailable, match="different Immich servers"),
    ):
        client.native_people(("primary", "partner"))


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "API key rejected"),
        (403, "person.read"),
        (404, "endpoint unavailable"),
        (400, "discovery failed"),
    ],
)
def test_discovery_refusals_are_explicit_not_fallbacks(monkeypatch, status, reason):
    FakeHousehold(
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster"},
        errors={"/api/people/users": status},
    ).install(monkeypatch)
    with (
        AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client,
        pytest.raises(AccountUnavailable, match=reason),
    ):
        client.native_people(("primary",))


def test_native_roster_follows_every_page(monkeypatch):
    server = FakeHousehold(
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "cluster"},
        roster={PRIMARY_KEY: [{"id": str(i), "name": f"Person {i}"} for i in range(5)]},
        people_page_size=2,
    ).install(monkeypatch)
    with AccessBoundClient(ImmichConfig(**immich_config(), native_sharing=True)) as client:
        native = client.native_people(("primary",))
    assert {person.id for person in native.roster} == {str(i) for i in range(5)}
    assert server.requests.count("/api/people") == 3


def test_preflight_explains_discovery_permission_failures(monkeypatch):
    from immich_memories.config_loader import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_accounts import check_native_sharing

    FakeHousehold(
        version={"major": 3, "minor": 3, "patch": 0, "prerelease": 1},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
        errors={"/api/people/users": 403},
    ).install(monkeypatch)
    result = check_native_sharing(
        Config(immich=ImmichConfig(**immich_config(), native_sharing=True))
    )
    assert result[0].status == CheckStatus.ERROR
    assert "person.read" in result[0].details
