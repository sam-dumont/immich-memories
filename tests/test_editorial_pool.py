"""Discovery hands every film the same complete, bounded source pool."""

from unittest.mock import create_autospec

import pytest

from immich_memories.analysis.editorial_pool import resolve_source_pool
from immich_memories.api.access_clients import AccountReadFailed
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.sync_client import SyncImmichClient
from tests.conftest import make_asset
from tests.test_editorial_source_route import photo


def test_context_discovery_remains_authoritative_for_ownership_and_membership():
    selected = photo("admitted")
    excluded = photo("excluded-owner")
    neighbour = photo("context-only")
    # WHY: only Immich reads are replaced; these ordinary stills require no companion read.
    client = create_autospec(SyncImmichClient, instance=True)
    pool = resolve_source_pool(client, [selected, excluded], context=[selected, neighbour])
    assert pool.selectable == (selected,)
    assert pool.context == (neighbour,)
    assert {source.id for source in pool.sources} == {selected.id, neighbour.id}
    client.get_asset.assert_not_called()


def test_captured_companion_keeps_its_proven_account_instead_of_the_stills_account():
    still = photo("shared-still", live="original-video").model_copy(
        update={"access_accounts": ("primary",)}
    )
    companion = make_asset("original-video", duration=2.7).model_copy(
        update={"access_accounts": ("partner",)}
    )
    # WHY: the known companion is already captured; no additional Immich request is needed.
    client = create_autospec(SyncImmichClient, instance=True)
    pool = resolve_source_pool(client, [still, companion])
    assert pool.selectable == (still,)
    assert pool.companions[0].access_accounts == ("partner",)
    client.get_asset.assert_not_called()


def test_repeated_live_links_are_resolved_once_and_never_offered_as_separate_clips():
    first = photo("first", live="motion")
    second = photo("second", live="motion")
    ordinary = photo("ordinary")
    companion = make_asset("motion", duration=2.5)
    # WHY: Immich returns the linked video once, however many stills reference it.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset.return_value = companion
    pool = resolve_source_pool(client, [first, second, ordinary, first])
    assert pool.selectable == (first, second, ordinary)
    assert pool.companions == (companion,)
    assert len(pool.sources) == 4
    client.get_asset.assert_called_once_with("motion")


def test_confirmed_missing_companion_is_visible_and_keeps_the_still(caplog):
    still = photo("still", live="gone")
    # WHY: a confirmed server-side absence differs from an interrupted or refused read.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset.side_effect = ImmichAPIError("not found", status_code=404)
    pool = resolve_source_pool(client, [still, photo("copy", live="gone")])
    assert len(pool.selectable) == 2
    assert pool.companions == ()
    assert "1 Live Photo companion(s) are unavailable" in caplog.text
    client.get_asset.assert_called_once_with("gone")


@pytest.mark.parametrize(
    "error", [ImmichAPIError("unavailable", 503), AccountReadFailed("refused")]
)
def test_failed_companion_read_cannot_silently_ship_a_still(error):
    # WHY: an Immich transport/account failure must remain a failed run.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset.side_effect = error
    with pytest.raises(type(error), match=str(error)):
        resolve_source_pool(client, [photo("still", live="motion")])


@pytest.mark.parametrize("companion", [photo("motion"), make_asset("wrong", duration=2.5)])
def test_a_companion_response_must_match_the_requested_video(companion):
    # WHY: malformed Immich metadata cannot be trusted as supporting footage.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset.return_value = companion
    with pytest.raises(ValueError, match="companion metadata disagrees"):
        resolve_source_pool(client, [photo("still", live="motion")])


@pytest.mark.parametrize("link", ["video", "another-video"])
def test_a_video_with_a_malformed_live_link_remains_an_ordinary_video(link):
    video = make_asset("video", duration=12).model_copy(update={"live_photo_video_id": link})
    # WHY: malformed Immich metadata must not trigger a companion read for a video.
    client = create_autospec(SyncImmichClient, instance=True)
    pool = resolve_source_pool(client, [video])
    assert pool.selectable == (video,)
    assert pool.companions == ()
    client.get_asset.assert_not_called()
