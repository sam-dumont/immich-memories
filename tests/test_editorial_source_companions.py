"""Live motion reaches the saved cut through every source entry point."""

import json
from unittest.mock import create_autospec

import pytest

from immich_memories.analysis.album_source import fetch_album_media
from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.analysis.editorial_motion_facts import RESIDUAL_PRODUCER
from immich_memories.analysis.editorial_pool import discover_source_context, resolve_source_pool
from immich_memories.analysis.editorial_preparation import PreparationResult
from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.selection_source import SourceScope
from immich_memories.analysis.selection_trace import Trace
from immich_memories.api.album_service import AlbumRef
from immich_memories.api.models import AssetType, MetadataSearchResult, ServerInfo, UserInfo
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.config_loader import Config
from immich_memories.store.cut_measurements import PendingMeasurements
from immich_memories.timeperiod import DateRange
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset
from tests.test_editorial_source_route import photo
from tests.test_special_event_source_routing import event_id


@pytest.mark.parametrize("product", ["album", "custom", "special_day"])
def test_every_source_route_keeps_live_motion_in_the_saved_cut(tmp_path, product):
    still = photo("moving-photo", live="companion")
    still.is_favorite = True
    companion = make_asset("companion", duration=2.7, file_created_at=still.file_created_at)
    # WHY: the Immich transport returns the album's photo and its separately linked video.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_assets_for_album.side_effect = lambda _album, *, asset_type, limit: (
        [still][:limit] if asset_type == AssetType.IMAGE else []
    )
    client.get_asset.return_value = companion
    client.generated_asset_ids.return_value = frozenset()
    client.list_albums.return_value = []
    client.get_server_info.return_value = ServerInfo(major=3, minor=3, patch=0)
    client.get_current_user.return_value = UserInfo(id="owner", email="owner@example.test")
    client.get_asset_ocr_text.return_value = None
    client.search_metadata.return_value = MetadataSearchResult()
    config = Config(tier="basic", cache={"directory": str(tmp_path / "cache")})
    window = DateRange(still.file_created_at, still.file_created_at)
    membership = (still.id,) if product == "special_day" else None
    if product == "album":
        media = fetch_album_media(
            client,
            AlbumRef(id="album", name="A day outside", asset_count=1),
            config=config,
            use_live_photos=True,
            use_photos=True,
        )
        pool = resolve_source_pool(client, media.videos + media.photos)
        client.get_videos_for_date_range.assert_not_called()
        client.get_photos_for_date_range.assert_not_called()
    else:
        neighbour = photo("outside-selection", at=still.file_created_at)
        neighbour.is_favorite = True
        client.get_photos_for_date_range.return_value = [still, neighbour]
        client.get_videos_for_date_range.return_value = []
        discovered = discover_source_context(
            client, SourceScope(date_ranges=(window,), asset_ids=membership)
        )
        pool = resolve_source_pool(client, [still], context=discovered)
    # Once discovered, every route must edit this same snapshot without reacquiring sources.
    client.get_videos_for_date_range.side_effect = AssertionError("editor repeated discovery")
    client.get_photos_for_date_range.side_effect = AssertionError("editor repeated discovery")
    client.get_asset.side_effect = AssertionError("editor repeated companion resolution")
    with PendingMeasurements(annotation_store()) as bank:
        bank.motion_residual(
            asset_id=still.id,
            producer=RESIDUAL_PRODUCER,
            source_digest=source_metadata_digest(still),
            measured={"residual": 9.0, "frames": 12},
        )
    # WHY: model acquisition is replaced by an already prepared library; motion is banked above.
    # WHY: external playback/pixel ports are absent; the real rules editor uses the saved facts.
    ports = EditorialRuntimePorts(
        load_people=dict,
        prepare_annotations=lambda *, assets, **_: PreparationResult(
            requested=len(assets), missing_by_producer={}, failures={}
        ),
        structure_ports_factory=lambda source: StructurePlannerPorts(
            judge=NoModelJudge(), thumbnail_hash=lambda _: None, rules=RuleStructureReader(source)
        ),
    )
    planner = build_editorial_planner(
        client=client,
        config=config,
        thumbnail_cache=ThumbnailCache(tmp_path / "previews"),
        context=EditorialRunContext(
            "source-test",
            "A day outside",
            product,
            (window,),
            15,
            tmp_path / "runs",
            album_ref="album" if product == "album" else None,
            special_event_id=event_id(membership) if membership else None,
            event_asset_ids=membership or (),
        ),
        source_pool=pool,
        ports=ports,
    )
    result = planner.plan_source(pool.selectable, trace=Trace(), include_live_photos=True)
    saved = json.loads((planner.last_attempt_directory / "plan.private.json").read_text())
    assert [(row["asset_id"], row["kind"]) for row in saved["carriers"]] == [
        (still.id, "live-motion")
    ]
    assert result.plan.selected_asset_ids == (still.id,)
    assert saved["carriers"][0]["video_ids"] == [companion.id]
    snapshot = json.loads(
        (planner.last_attempt_directory / "source-snapshot.private.json").read_text()
    )
    assert snapshot["captured_companion_count"] == 1
    assert snapshot["missing_companion_ids"] == []
