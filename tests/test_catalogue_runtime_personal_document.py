"""The --ask period accounts read the same personal-document facts a cut would (#2062)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from immich_memories.analysis.catalogue_runtime import _screen_documents
from immich_memories.analysis.editorial_source import library_source_scope
from immich_memories.api.models import Asset, ServerInfo
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.timeperiod import DateRange
from tests.annotation_rows import add_rows

CONFIG = Config(tier="gpu")
START = datetime(2021, 3, 1, 10, tzinfo=UTC)


class _FakeOcrClient:
    """A stub Immich server. WHY: replaces a real Immich 2.2+ server for the OCR port."""

    def __init__(self, text_by_asset: dict[str, str]) -> None:
        self._text = text_by_asset

    def get_server_info(self) -> ServerInfo:
        return ServerInfo(major=2, minor=2, patch=0)

    def get_asset_ocr_text(self, asset_id: str) -> str | None:
        return self._text.get(asset_id)


def _card() -> Asset:
    return Asset(
        id="card-1",
        type="IMAGE",
        file_created_at=START,
        file_modified_at=START,
        updated_at=START,
        original_file_name="IMG_card.JPG",
        width=3000,
        height=2000,
    )


def _scope():
    window = DateRange(start=START, end=START + timedelta(days=1))
    return library_source_scope(None, CONFIG, (window,), accept_any_provenance=True)


def test_the_period_account_pass_withholds_a_document_through_the_given_client() -> None:
    add_rows(
        open_store(),
        "head_facts",
        {
            "asset_id": "card-1",
            "head": "frame_kind",
            "version": CONFIG.editorial.head_versions["frame_kind"],
            "label": "meaningful_record",
        },
    )
    client = _FakeOcrClient({"card-1": "Numéro national: 85.04.12-345-67"})

    exclusions = _screen_documents([_card()], _scope(), CONFIG, None, client)

    assert exclusions == {"card-1": "personal-document"}


def test_without_a_client_the_period_account_pass_skips_the_ocr_signal_only() -> None:
    add_rows(
        open_store(),
        "head_facts",
        {
            "asset_id": "card-1",
            "head": "frame_kind",
            "version": CONFIG.editorial.head_versions["frame_kind"],
            "label": "meaningful_record",
        },
    )

    exclusions = _screen_documents([_card()], _scope(), CONFIG, None, None)

    assert exclusions == {}
