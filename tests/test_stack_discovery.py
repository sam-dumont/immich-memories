"""No stack.read, or a pre-stacks server, keeps today's behaviour (no stack folding)."""

from __future__ import annotations

from immich_memories.api.accounts import OpenAccount
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Stack, StackAssetRef
from immich_memories.api.stack_discovery import discover_stack_map


class _StubClient:
    """Stands in for `SyncImmichClient.get_stacks`, the only call this module makes."""

    def __init__(self, stacks=None, error: Exception | None = None) -> None:
        self._stacks = stacks or []
        self._error = error

    def get_stacks(self) -> list[Stack]:
        if self._error is not None:
            raise self._error
        return self._stacks


def _account(name: str, client: _StubClient) -> OpenAccount:
    return OpenAccount(name=name, client=client, user=None, api_version=None)  # type: ignore[arg-type]


def test_every_member_maps_to_its_stacks_primary():
    stack = Stack(
        id="s1",
        primaryAssetId="edit",
        assets=[StackAssetRef(id="edit"), StackAssetRef(id="original")],
    )
    opened = {"primary": _account("primary", _StubClient(stacks=[stack]))}

    assert discover_stack_map(opened) == {"original": "edit"}


def test_a_403_falls_back_to_an_empty_map():
    # WHY: the real boundary is Immich's /stacks endpoint; a 403 is the stand-in for a
    # key without stack.read, which must not fail the run.
    forbidden = ImmichAPIError("Forbidden", status_code=403)
    opened = {"primary": _account("primary", _StubClient(error=forbidden))}

    assert discover_stack_map(opened) == {}


def test_each_accounts_stacks_are_merged():
    primary_stack = Stack(
        id="s1",
        primaryAssetId="a-edit",
        assets=[StackAssetRef(id="a-edit"), StackAssetRef(id="a-original")],
    )
    partner_stack = Stack(
        id="s2",
        primaryAssetId="b-edit",
        assets=[StackAssetRef(id="b-edit"), StackAssetRef(id="b-original")],
    )
    opened = {
        "primary": _account("primary", _StubClient(stacks=[primary_stack])),
        "partner": _account("partner", _StubClient(stacks=[partner_stack])),
    }

    assert discover_stack_map(opened) == {"a-original": "a-edit", "b-original": "b-edit"}
