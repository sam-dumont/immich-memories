"""A household run asks for every copy it found; the cut reads the copy kept (#1500).

Discovery reads each chosen account, so the pictures it hands the editor include both
accounts' copies of a shared picture. The source folds them into one; asking for the
absorbed copy asks for the picture, not for something the source never captured.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

from immich_memories.analysis.editorial_source_route import metadata_demand
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.api.models import AssetType
from tests.conftest import make_asset

TAKEN = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)


def _photo(asset_id: str, owner: str, content: str):
    checksum = base64.b64encode(hashlib.sha1(content.encode()).digest()).decode()  # noqa: S324
    return make_asset(asset_id, file_created_at=TAKEN).model_copy(
        update={"type": AssetType.IMAGE, "owner_id": owner, "checksum": checksum}
    )


def test_asking_for_an_absorbed_copy_asks_for_the_kept_one():
    ours, theirs = _photo("a-copy", "owner-a", "shared"), _photo("b-copy", "owner-b", "shared")
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(), primary_owner_id="owner-a"),
        EditorialDependencies(source_fetcher=lambda _scope: (ours, theirs)),
    )

    rows = metadata_demand(prepared, [theirs], photo_seconds=4.0)
    both = metadata_demand(prepared, [theirs, ours], photo_seconds=4.0)

    assert prepared.candidate_ids == ("a-copy",)
    assert [row.clip.asset.id for row in rows] == ["a-copy"]
    assert [row.clip.asset.id for row in both] == ["a-copy"]
