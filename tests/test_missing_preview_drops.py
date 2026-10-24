"""A picture whose preview Immich no longer has drops; the film goes on.

Immich answers 404 "Asset media not found" for an asset whose preview file is gone.
The forwarded-copy fallback hashes previews to tell a copy from its original, and
that 404 used to escape and fail the whole On This Day film. A missing preview
reads as no preview, the way preparation already treats it; any other Immich error
still stops the run.

Preparation reads previews through the same port, so a picture Immich never made a
preview for (#2880) leaves the film there too, instead of failing it as unprepared.
"""

from __future__ import annotations

import pytest

from immich_memories.analysis.preparation.previews import (
    PREVIEW_UNAVAILABLE,
    ensure_preview,
    preview_refused,
)
from immich_memories.analysis.preparation.thumbnail_hashes import CachedThumbnailHasher
from immich_memories.analysis.runtime.ports import EditorialRuntimePorts
from immich_memories.api.immich import ImmichAPIError, ImmichNotFoundError
from tests.conftest import make_asset
from tests.test_editorial_preparation import asset, preview, run, successful_ports


class _ImmichWithoutSomePreviews:
    """Stands in for Immich. WHY: Immich is the external boundary; no network here."""

    def __init__(self, missing: set[str], error: Exception | None = None) -> None:
        self._missing = missing
        self._error = error or ImmichNotFoundError("Resource not found", status_code=404)

    def get_asset(self, asset_id: str):
        return make_asset(asset_id)

    def get_asset_thumbnail(
        self, asset_id: str, size: str = "preview", *, edited: bool = False
    ) -> bytes:
        if asset_id in self._missing:
            raise self._error
        return preview()


def test_a_preview_immich_no_longer_has_reads_as_no_preview():
    client = _ImmichWithoutSomePreviews(missing={"gone"})

    read = EditorialRuntimePorts().preview_reader(client, {"gone": False, "here": False})

    assert read("gone") is None
    assert read("here") == preview()


def test_the_look_alike_hash_of_a_missing_preview_is_unavailable_not_a_failed_film(tmp_path):
    client = _ImmichWithoutSomePreviews(missing={"gone"})
    hasher = CachedThumbnailHasher(
        tmp_path / "hashes.sqlite",
        EditorialRuntimePorts().preview_reader(client, {"gone": False}),
    )

    assert hasher("gone") is None


def test_any_other_immich_error_still_stops_the_run():
    client = _ImmichWithoutSomePreviews(
        missing={"broken"}, error=ImmichAPIError("Internal server error", status_code=500)
    )

    read = EditorialRuntimePorts().preview_reader(client, {"broken": False})

    with pytest.raises(ImmichAPIError):
        read("broken")


def _prepare_through_the_port(tmp_path, client):
    ids = ("gone", "here")
    return run(
        tmp_path,
        assets=[asset(asset_id) for asset_id in ids],
        ports=successful_ports([]),
        fetch_preview=EditorialRuntimePorts().preview_reader(client, dict.fromkeys(ids, False)),
    )


def test_preparation_leaves_out_a_picture_immich_never_made_a_preview_for(tmp_path):
    result = _prepare_through_the_port(tmp_path, _ImmichWithoutSomePreviews(missing={"gone"}))

    assert result.unservable_sources == {"gone": PREVIEW_UNAVAILABLE}
    assert result.complete
    assert not result.producer_failures


def test_preparation_still_counts_any_other_immich_error_as_unfinished(tmp_path):
    client = _ImmichWithoutSomePreviews(
        missing={"gone"}, error=ImmichAPIError("Internal server error", status_code=500)
    )

    result = _prepare_through_the_port(tmp_path, client)

    assert not result.unservable_sources
    assert not result.complete


def test_an_empty_preview_is_a_failed_read_not_immich_s_answer(tmp_path):
    with pytest.raises(FileNotFoundError) as raised:
        ensure_preview(tmp_path / "empty.jpg", "empty", lambda _asset_id: b"")

    assert not preview_refused(raised.value)
