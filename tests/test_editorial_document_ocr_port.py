"""`document_ocr_port` degrades to no OCR signal rather than hold the whole library (#2062).

Round 3: the owner's rule is a cold year under an hour, so a run must never read every
asset's OCR text to find the few personal documents in it. These tests hold the two levers
that bound that cost: memoising a read per asset id, and narrowing to Immich's own keyword
search before paying for the expensive per-asset read at all.
"""

from immich_memories.analysis.editorial_document_ocr import document_ocr_port
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import ServerInfo


class _SearchHit:
    """WHY: stands in for Immich's `Asset`; `ImmichPrintedText` only reads `.id`."""

    def __init__(self, asset_id: str) -> None:
        self.id = asset_id


class _SearchResult:
    """WHY: stands in for `MetadataSearchResult`; only `.all_assets`/`.next_page` are read."""

    def __init__(self, asset_ids: frozenset[str]) -> None:
        self.all_assets = [_SearchHit(asset_id) for asset_id in asset_ids]
        self.next_page: str | None = None


class _Client:
    def __init__(
        self, server_info=None, text_by_asset=None, *, raise_on_text=None, searchable=False
    ):
        self._server_info = server_info
        self._text = text_by_asset or {}
        self._raise_on_text = raise_on_text
        self.reads: list[str] = []
        self._hits_by_word: dict[str, frozenset[str]] = {}
        self.search_calls: list[str] = []
        if searchable:
            self.search_metadata = self._search_metadata

    def get_server_info(self) -> ServerInfo:
        return self._server_info

    def get_asset_ocr_text(self, asset_id: str) -> str | None:
        self.reads.append(asset_id)
        if self._raise_on_text is not None:
            raise self._raise_on_text
        return self._text.get(asset_id)

    def hold(self, word: str, asset_ids: frozenset[str]) -> None:
        self._hits_by_word[word] = asset_ids

    def _search_metadata(self, *, ocr: str, page: int = 1, size: int = 1000, **_kwargs):
        self.search_calls.append(ocr)
        return _SearchResult(self._hits_by_word.get(ocr, frozenset()))


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


def test_the_same_asset_is_never_read_twice_across_build_refresh_and_audience():
    # One port, shared the way `ports.document_ocr_text` is shared across the material
    # build, a candidate refresh and the audience gate: a round trip per asset, once.
    client = _Client(ServerInfo(major=2, minor=2, patch=0), {"a": "PASSPORT"})
    port = document_ocr_port(client)
    assert port is not None

    for _ in range(3):  # stands in for build, refresh and the audience gate each asking
        assert port("a") == "PASSPORT"
    assert client.reads == ["a"]


def test_the_bulk_keyword_search_narrows_which_assets_pay_for_a_real_read():
    client = _Client(ServerInfo(major=2, minor=2, patch=0), {"card": "PASSPORT"}, searchable=True)
    client.hold("passport", frozenset({"card"}))

    port = document_ocr_port(client)
    assert port is not None

    assert port("card") == "PASSPORT"
    assert port("menu") is None
    # Only the one asset the bulk search actually turned up pays for a real OCR read.
    assert client.reads == ["card"]
    assert client.search_calls  # the bulk search ran, not a per-asset search


def test_the_bulk_search_runs_once_even_when_many_assets_are_asked():
    client = _Client(ServerInfo(major=2, minor=2, patch=0), searchable=True)

    port = document_ocr_port(client)
    assert port is not None

    for asset_id in ("a", "b", "c"):
        port(asset_id)

    assert len(client.search_calls) == len(set(client.search_calls))
    first_pass = list(client.search_calls)
    port("d")
    assert client.search_calls == first_pass
