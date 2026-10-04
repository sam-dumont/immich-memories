"""Fresh, server-scoped identity evidence; owner reads and saved bindings stay intact."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace

import httpx
from pydantic import ValidationError

from immich_memories.api.accounts import AccountUnavailable, OpenAccount
from immich_memories.api.compatibility import UnsupportedImmichVersion
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Person, ServerInfo

logger = logging.getLogger(__name__)


@dataclass
class NativePeople:
    """Transient evidence, rebuilt each run without rewriting the canonical people store."""

    opened: Mapping[str, OpenAccount] = field(default_factory=dict)
    binding_servers: Mapping[str, str] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)
    modes: dict[str, str] = field(default_factory=dict)
    people: dict[str, Person] = field(default_factory=dict)
    scopes: dict[str, frozenset[str]] = field(default_factory=dict)
    rosters: dict[str, set[str]] = field(default_factory=dict)
    expected: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def roster(self) -> list[Person]:
        """One record per proven server identity; names never join records."""
        return list(self.people.values())

    def accounts_for(self, face: str, account: str) -> frozenset[str]:
        """Check a saved binding before expanding it with fresh upstream evidence."""
        if account not in self.rosters:
            return self._shared_binding(face, account)
        if face not in self.rosters[account]:
            self._verify(face, account)
        if face not in self.rosters[account]:
            raise AccountUnavailable(
                f"Immich account {account!r} no longer exposes person {face!r}. "
                "Check people access or rebind after an upstream merge; "
                "saved identities and confirmations have been kept."
            )
        return self.scopes[face]

    def _shared_binding(self, face: str, account: str) -> frozenset[str]:
        server = self.binding_servers.get(account)
        selected = frozenset(
            name
            for name, opened in self.opened.items()
            if self.modes[name] != "legacy" and opened.client.base_url == server
        )
        for name in sorted(selected):
            if face not in self.rosters[name]:
                self._verify(face, name)
        return self.scopes.get(face, frozenset()) & selected

    def require_complete(self, faces: Collection[str]) -> None:
        """A named person's aliases must cover its selected native cluster members.

        Separate explicit bindings can supply that coverage, as can one shared identity.
        Without this check a revoked share would look like an empty partner episode.
        """
        for face in faces:
            for name in self.expected.get(face, frozenset()) - self.scopes.get(face, frozenset()):
                self._verify(face, name)
        expected = frozenset().union(*(self.expected.get(face, ()) for face in faces))
        actual = frozenset().union(*(self.scopes.get(face, ()) for face in faces))
        if missing := expected - actual:
            raise AccountUnavailable(
                f"Native people access is missing for selected accounts: {', '.join(sorted(missing))}. "
                "Share the person in Immich or keep explicit bindings with native_sharing disabled. "
                "No partial source will be used."
            )

    def _verify(self, face: str, name: str) -> None:
        account = self.opened[name]
        try:
            person = account.client.get_person(face)
        except ImmichAPIError as error:
            if error.status_code == 404:
                return
            raise AccountUnavailable(
                f"Cannot verify person {face!r} or people access for account {name!r}. "
                "Check access or rebind after an upstream merge; no partial source will be used"
            ) from error
        if person.id != face:
            raise AccountUnavailable(
                "Immich changed this person ID; rebind it explicitly to preserve the saved identity"
            )
        cluster = (
            frozenset({name})
            if self.modes[name] == "legacy"
            else _cluster_accounts(account, self.opened)
        )
        self._record(person, account, cluster)

    def _record(self, person: Person, account: OpenAccount, cluster: frozenset[str]) -> None:
        face, name = person.id, account.name
        origin = account.client.base_url
        if face in self.origins and self.origins[face] != origin:
            raise AccountUnavailable(
                "The same person ID occurs on different Immich servers; use separate runs"
            )
        self.origins[face] = origin
        if face not in self.people or not self.people[face].name:
            self.people[face] = person
        self.rosters[name].add(face)
        self.expected[face] = cluster
        scope = cluster if self.modes[name] == "cluster" else frozenset({name})
        self.scopes[face] = self.scopes.get(face, frozenset()) | scope


def discover_native_people(
    opened: Mapping[str, OpenAccount], *, binding_servers: Mapping[str, str]
) -> NativePeople | None:
    """Check versions, rosters and grants on the selected connections, without changing grants."""
    result = NativePeople(binding_servers=binding_servers)
    current = {
        name: replace(account, user=account.client.get_current_user())
        for name, account in opened.items()
    }
    result.opened = current
    for name, account in current.items():
        version = account.client.get_server_info()
        result.modes[name] = native_mode(version)
        if result.modes[name] == "legacy":
            logger.warning(
                "Native sharing needs Immich 3.2 or later; account %s uses %s. Keeping existing bindings.",
                name,
                version.version_string,
            )
    if all(mode == "legacy" for mode in result.modes.values()):
        return None
    for name, account in current.items():
        mode = result.modes[name]
        roster = _read_roster(account, mode)
        result.rosters[name] = set()
        cluster = frozenset({name}) if mode == "legacy" else _cluster_accounts(account, current)
        for person in roster:
            result._record(person, account, cluster)
    return result


def native_mode(version: ServerInfo) -> str:
    """Minor capabilities come from the server, never from the API-major override."""
    if version.major not in (2, 3):
        raise UnsupportedImmichVersion(
            f"Native sharing is unsupported on Immich {version.version_string}; an api_version override does not enable native capabilities"
        )
    if version.major == 2 or version.minor < 2:
        return "legacy"
    if version.minor > 3 or version.prerelease not in (None, 0, "", 1):
        raise UnsupportedImmichVersion(
            f"Native sharing is unvalidated on Immich {version.version_string}"
        )
    if version.prerelease and (version.minor, version.patch) != (3, 0):
        raise UnsupportedImmichVersion(
            "Only Immich 3.3.0-rc.1 is validated for experimental native sharing"
        )
    return "cluster" if version.minor == 2 else "people"


def _cluster_accounts(account: OpenAccount, opened: Mapping[str, OpenAccount]) -> frozenset[str]:
    same_server = {
        name: other
        for name, other in opened.items()
        if other.client.base_url == account.client.base_url
    }
    cluster = account.user.cluster_group_id
    if not cluster or any(other.user.cluster_group_id != cluster for other in same_server.values()):
        raise AccountUnavailable(
            "Native sharing needs the selected accounts on each server in the same cluster group. "
            "Check membership, or use existing bindings with native_sharing disabled."
        )
    return frozenset(same_server)


def _read_roster(account: OpenAccount, mode: str) -> list[Person]:
    reading_grants = mode == "people"
    try:
        shares = []
        if mode == "people":
            logger.warning(
                "Immich 3.3 native people sharing is experimental; validated against 3.3.0-rc.1 only"
            )
            shares = account.client.get_people_access()
        reading_grants = False
        roster = account.client.get_all_people(with_hidden=True)
        known = {person.id for person in roster}
        shared = {
            share.person_id
            for share in shares
            if account.user.id in (share.shared_by_id, share.shared_with_id)
        }
        for face in sorted(shared - known):
            person = account.client.get_person(face)
            if person.id != face:
                raise AccountUnavailable("A shared person changed identity; rebind it explicitly")
            roster.append(person)
        return roster
    except (ImmichAPIError, httpx.HTTPError, ValidationError) as error:
        status = error.status_code if isinstance(error, ImmichAPIError) else None
        reason = {
            401: "API key rejected",
            403: "missing person.read permission or revoked people access",
            404: "sharing endpoint unavailable on the reported server version"
            if reading_grants
            else "person or roster unavailable; check for deleted people or revoked access",
        }.get(status or 0, "sharing discovery failed; retry after checking the server")
        raise AccountUnavailable(
            f"Native sharing for account {account.name!r}: {reason}. No partial source will be used."
        ) from error
