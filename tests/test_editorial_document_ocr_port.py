"""`document_ocr_port` asks Immich only when the answer can change a verdict (#2062, #2711).

The owner's rule is a cold year under an hour, so a run must never read every asset's OCR
text to find the few personal documents in it. `personal_document` reads OCR text only for a
frame its head leaves document-like, so the port reads only those frames, once each per
client, and never searches the whole library by keyword.
"""

from immich_memories.analysis.facts.carrier_eligibility import (
    excluded_carrier_sources,
    personal_document,
)
from immich_memories.analysis.preparation.document_ocr import document_ocr_port
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import ServerInfo

_SERVER = ServerInfo(major=2, minor=2, patch=0)
_MRZ = "PASSPORT P<UTOSAMPLE<<ALEX<<<<<<<<<<<<<<<<<<<<<<<<<<"


class _Client:
    """WHY: stands in for the run's Immich client; counts every request the port makes."""

    def __init__(self, server_info=_SERVER, text_by_asset=None, *, raise_on_text=None):
        self._server_info = server_info
        self._text = text_by_asset or {}
        self._raise_on_text = raise_on_text
        self.reads: list[str] = []
        self.version_reads = 0
        self.search_calls: list[str] = []

    def get_server_info(self) -> ServerInfo:
        self.version_reads += 1
        return self._server_info

    def get_asset_ocr_text(self, asset_id: str) -> str | None:
        self.reads.append(asset_id)
        if self._raise_on_text is not None:
            raise self._raise_on_text
        return self._text.get(asset_id)

    def search_metadata(self, *, ocr: str | None = None, **_kwargs):
        self.search_calls.append(str(ocr))
        raise AssertionError("the OCR port must not search the library")


def test_a_client_with_no_ocr_read_or_version_read_has_no_ocr_port():
    assert document_ocr_port(object()) is None
    assert document_ocr_port(None) is None


def test_a_server_older_than_2_2_has_no_ocr_port():
    assert document_ocr_port(_Client(ServerInfo(major=2, minor=1, patch=9))) is None


def test_a_document_like_frame_is_read_on_a_2_2_server():
    client = _Client(text_by_asset={"a": "PASSPORT"})
    port = document_ocr_port(client)
    assert port is not None
    assert port("a", True) == "PASSPORT"
    assert port("missing", True) is None


def test_a_version_read_failure_disables_the_signal_without_raising():
    class _BrokenVersion:
        def get_server_info(self):
            raise ImmichAPIError("down")

        def get_asset_ocr_text(self, asset_id):
            return "unreachable"

    assert document_ocr_port(_BrokenVersion()) is None


def test_an_ocr_read_failure_disables_the_signal_for_the_rest_of_the_run_not_just_one_asset():
    client = _Client(raise_on_text=ImmichAPIError("flaky"))
    port = document_ocr_port(client)
    assert port is not None

    # The first failing read disables the port; nothing after it retries or raises, so a
    # transient Immich error never holds the whole library while other signals still apply.
    assert port("a", True) is None
    client._raise_on_text = None
    client._text = {"a": "PASSPORT"}
    assert port("a", True) is None
    assert port("b", True) is None
    assert client.reads == ["a"]


def test_a_non_document_frame_costs_no_request_at_all():
    # Its answer is ignored by `personal_document`, so asking would only cost a round trip.
    client = _Client(text_by_asset={"menu": "PASSPORT"})
    port = document_ocr_port(client)
    assert port is not None

    assert port("menu", False) is None
    assert client.reads == []
    assert client.search_calls == []


def test_the_same_asset_is_read_once_however_many_callers_build_a_port_on_the_client():
    # The material build, a candidate refresh, the audience gate and the period account
    # each ask for a port: one client, one version read, one round trip per asset.
    client = _Client(text_by_asset={"a": "PASSPORT"})

    for _ in range(3):
        port = document_ocr_port(client)
        assert port is not None
        assert port("a", True) == "PASSPORT"

    assert client.reads == ["a"]
    assert client.version_reads == 1


def test_another_client_gets_its_own_reads():
    first = _Client(text_by_asset={"a": "PASSPORT"})
    second = _Client(text_by_asset={"a": "VISA"})
    first_port, second_port = document_ocr_port(first), document_ocr_port(second)
    assert first_port is not None
    assert second_port is not None

    assert first_port("a", True) == "PASSPORT"
    assert second_port("a", True) == "VISA"


def test_the_carrier_rule_reaches_the_same_verdicts_while_reading_only_document_frames():
    # The audit behind #2711: the OCR text of a non-document frame never decides anything.
    # A people frame whose OCR reads like a passport stays; a document frame that reads one
    # goes; a frame no head ran on is read, since OCR is the strongest evidence it has.
    client = _Client(text_by_asset=dict.fromkeys(("party", "scan", "bare"), _MRZ))
    port = document_ocr_port(client)
    heads = {
        "party": {"frame_kind": "people_moment"},
        "scan": {"frame_kind": "screen_or_document"},
        "bare": {},
    }

    excluded = excluded_carrier_sources(
        dict.fromkeys(heads, "a picture"), heads_of=heads, ocr_text_of=port
    )

    assert excluded == {"scan": "personal-document", "bare": "personal-document"}
    assert not personal_document("", heads["party"], _MRZ)
    assert sorted(client.reads) == ["bare", "scan"]
    assert client.search_calls == []
