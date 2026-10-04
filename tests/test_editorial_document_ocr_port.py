"""`document_ocr_port` degrades to no OCR signal rather than hold the whole library (#2062)."""

from immich_memories.analysis.editorial_carrier_eligibility import document_ocr_port
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import ServerInfo


class _Client:
    def __init__(self, server_info=None, text_by_asset=None, *, raise_on_text=None):
        self._server_info = server_info
        self._text = text_by_asset or {}
        self._raise_on_text = raise_on_text

    def get_server_info(self) -> ServerInfo:
        return self._server_info

    def get_asset_ocr_text(self, asset_id: str) -> str | None:
        if self._raise_on_text is not None:
            raise self._raise_on_text
        return self._text.get(asset_id)


def test_a_client_with_no_search_or_version_read_has_no_ocr_port():
    assert document_ocr_port(object()) is None
    assert document_ocr_port(None) is None


def test_a_server_older_than_2_2_has_no_ocr_port():
    client = _Client(ServerInfo(major=2, minor=1, patch=9))
    assert document_ocr_port(client) is None


def test_a_server_at_2_2_reads_ocr_text():
    client = _Client(ServerInfo(major=2, minor=2, patch=0), {"a": "PASSPORT"})
    port = document_ocr_port(client)
    assert port is not None
    assert port("a") == "PASSPORT"
    assert port("missing") is None


def test_a_version_read_failure_disables_the_signal_without_raising():
    class _BrokenVersion:
        def get_server_info(self):
            raise ImmichAPIError("down")

        def get_asset_ocr_text(self, asset_id):
            return "unreachable"

    assert document_ocr_port(_BrokenVersion()) is None


def test_an_ocr_read_failure_disables_the_signal_for_the_rest_of_the_run_not_just_one_asset():
    client = _Client(ServerInfo(major=2, minor=2, patch=0), raise_on_text=ImmichAPIError("flaky"))
    port = document_ocr_port(client)
    assert port is not None

    # The first failing read disables the port; nothing after it retries or raises, so a
    # transient Immich error never holds the whole library while other signals still apply.
    assert port("a") is None
    client._raise_on_text = None
    client._text = {"a": "PASSPORT"}
    assert port("a") is None
