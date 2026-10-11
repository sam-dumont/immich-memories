"""The shared Immich fakes refuse what the real Immich and the real client refuse.

The request rules come from the Immich OpenAPI specs, trimmed to the endpoints the app
calls (`tests/fixtures/immich-openapi/contract.json`, `scripts/trim_immich_openapi.py`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pytest

from tests.immich_fakes import (
    CONTRACT,
    RELEASES,
    V2,
    V3,
    ImmichWire,
    fake_immich_client,
    request_problems,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from trim_immich_openapi import ENDPOINTS  # noqa: E402

# UUIDs as Immich v3.3 requires them: version 4, RFC variant.
PERSON = "0f8e4a52-3c1d-4b6e-9a7f-2d5c8b1e6f30"
ALBUM = "4f1c9a7e-2b3d-4c5e-8f90-1a2b3c4d5e6f"


def test_the_contract_holds_every_supported_release():
    assert RELEASES == ("v2.7.5", "v3.2.2", "v3.3.0")
    assert V2 == ("v2.7.5",) and V3 == ("v3.2.2", "v3.3.0")


def test_the_committed_contract_matches_the_endpoint_list_it_was_trimmed_for():
    """Stale contract: rerun scripts/trim_immich_openapi.py after changing ENDPOINTS."""
    wanted = {f"{method} {path}" for method, path in ENDPOINTS}
    for release, endpoints in CONTRACT.items():
        assert set(endpoints) <= wanted, release
    # An endpoint may be newer than a release (people/users is v3.3), never missing from all.
    assert set().union(*CONTRACT.values()) == wanted


_CALL = re.compile(r'_request\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*f?"(/[^"]+)"')
_NOT_IMMICH = {("GET", "/health"), ("POST", "/jobs")}


def test_every_immich_call_in_the_client_is_in_the_contract():
    calls = set()
    for source in (ROOT / "src" / "immich_memories" / "api").glob("*.py"):
        for method, path in _CALL.findall(source.read_text(encoding="utf-8")):
            calls.add((method, re.sub(r"\{[^}]+\}", "{id}", re.sub(r"^/api(?=/)", "", path))))

    assert calls, "the pattern no longer finds the client's requests"
    assert calls - _NOT_IMMICH <= set(ENDPOINTS)


def test_a_client_fake_refuses_a_keyword_the_real_client_does_not_take():
    client = fake_immich_client()

    with pytest.raises(TypeError):
        client.get_videos_for_date_range(date_range=None, not_a_real_keyword=True)


def test_a_client_fake_refuses_a_method_the_real_client_does_not_have():
    client = fake_immich_client()

    with pytest.raises(AttributeError):
        client.search_everything()


def test_a_well_formed_metadata_search_passes_on_every_release():
    body = {
        "page": 2,
        "size": 1000,
        "withExif": True,
        "personIds": [PERSON],
        "albumIds": [ALBUM],
        "type": "VIDEO",
        "takenAfter": "2024-06-01T00:00:00.000Z",
    }

    assert request_problems("POST", "/api/search/metadata", {}, body) == []


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ({"page": "2", "size": 100}, "v3.2.2/v3.3.0: page must be integer"),
        ({"page": True, "size": 100}, "v3.2.2/v3.3.0: page must be integer"),
        ({"page": 1.5}, "v3.2.2/v3.3.0: page must be integer"),
        ({"page": 1, "size": 5000}, "size must be at most 1000"),
        ({"page": 0}, "page must be at least 1"),
        ({"personIds": ["subject"]}, "personIds[] must be a UUID"),
        ({"type": "PHOTO"}, "type must be one of"),
        ({"takenAfter": "last tuesday"}, "takenAfter must be a date-time"),
        ({"takenAfter": "2024-06-01"}, "v3.2.2/v3.3.0: takenAfter does not match the pattern"),
        ({"withExif": "yes"}, "withExif must be boolean"),
        ({"personIds": None}, "personIds must not be null"),
        ({"rating": 0}, "v3.2.2/v3.3.0: rating must be at least 1"),
    ],
)
def test_a_metadata_search_immich_would_refuse_is_refused(body, problem):
    problems = request_problems("POST", "/api/search/metadata", {}, body)

    assert any(p.startswith(problem) for p in problems), problems


def test_v3_takes_only_version_4_uuids():
    version_1 = "6a1f0c3e-58d2-1b7a-9e41-0c2d7f8b3a15"

    problems = request_problems("GET", f"/api/people/{version_1}", {}, None)

    assert problems == [
        f"v3.2.2/v3.3.0: id does not match the pattern Immich requires, got {version_1!r}"
    ]


def test_query_parameters_are_checked_as_immich_converts_them():
    assert request_problems("GET", "/api/people", {"page": "1", "withHidden": "false"}, None) == []
    assert request_problems("GET", "/api/people", {"page": "one"}, None, releases=V3) == [
        "page must be integer, got 'one'"
    ]
    assert request_problems("GET", "/api/timeline/bucket", {}, None) == ["timeBucket is required"]


def test_ids_in_paths_and_required_fields_are_checked():
    assert request_problems("GET", "/api/assets/not-a-uuid/original", {}, None)
    assert request_problems("PUT", f"/api/albums/{ALBUM}/assets", {}, {}) == ["ids is required"]


def test_readable_fixture_ids_can_be_allowed_while_types_are_still_checked():
    assert request_problems("GET", "/api/assets/home-breakfast-01", {}, None, uuid_ids=False) == []
    assert (
        request_problems(
            "POST", "/api/search/metadata", {}, {"personIds": ["person-alex"]}, uuid_ids=False
        )
        == []
    )
    assert request_problems(
        "POST", "/api/search/metadata", {}, {"personIds": "person-alex"}, uuid_ids=False
    ) == ["personIds must be an array, got 'person-alex'"]


def test_the_wire_answers_a_refused_request_with_a_400_and_records_it():
    wire = ImmichWire(
        lambda _request: httpx.Response(200, json={"assets": {"items": []}}), releases=V3
    )

    with httpx.Client(base_url="https://immich.test", transport=wire.transport) as client:
        refused = client.post("/api/search/metadata", json={"page": "1"})
        served = client.post("/api/search/metadata", json={"page": 1})

    assert refused.status_code == 400
    assert served.status_code == 200
    assert wire.violations == ["POST /api/search/metadata: page must be integer, got '1'"]
    with pytest.raises(AssertionError):
        wire.assert_clean()


@pytest.mark.parametrize(
    ("version", "releases"),
    [("V2", V2), ("V3", V3)],
)
def test_the_upload_form_the_client_builds_is_what_each_release_requires(
    tmp_path, version, releases
):
    from datetime import UTC, datetime

    from immich_memories.api.album_service import build_upload_fields
    from immich_memories.api.compatibility import ResolvedApiVersion

    film = tmp_path / "memory.mp4"
    film.write_bytes(b"film")
    fields = build_upload_fields(
        ResolvedApiVersion[version], film, datetime(2024, 6, 1, 12, tzinfo=UTC)
    )

    form = {**fields, "assetData": film.name}
    assert request_problems("POST", "/api/assets", {}, None, form=form, releases=releases) == []


def test_v2_requires_the_device_identity_that_v3_no_longer_defines():
    form = {
        "assetData": "memory.mp4",
        "fileCreatedAt": "2024-06-01T12:00:00+00:00",
        "fileModifiedAt": "2024-06-01T12:00:00+00:00",
    }

    assert request_problems("POST", "/api/assets", {}, None, form=form) == [
        "v2.7.5: deviceAssetId is required",
        "v2.7.5: deviceId is required",
    ]
    assert "deviceId" not in CONTRACT["v3.3.0"]["POST /assets"]["form"]


@pytest.mark.parametrize(
    ("method", "path", "query", "body", "undefined"),
    [
        ("GET", "/api/timeline/buckets", {"size": "MONTH"}, None, "size"),
        ("GET", "/api/timeline/buckets", {"type": "VIDEO"}, None, "type"),
        ("POST", "/api/search/metadata", {}, {"page": 1, "pageSize": 10}, "pageSize"),
        ("PUT", f"/api/albums/{ALBUM}/assets", {}, {"ids": [PERSON], "albumId": ALBUM}, "albumId"),
    ],
)
def test_a_parameter_no_release_defines_is_refused(method, path, query, body, undefined):
    """Immich drops it silently, so the request would mean less than the code thinks."""
    problems = request_problems(method, path, query, body)

    assert f"{undefined} is not a parameter Immich defines" in problems


def test_a_parameter_only_some_releases_define_is_refused_by_the_others():
    problems = request_problems("GET", "/api/albums", {"shared": "true"}, None)

    assert problems == ["v3.2.2/v3.3.0: shared is not a parameter Immich defines"]
