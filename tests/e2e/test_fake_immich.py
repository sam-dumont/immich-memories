"""Contract tests for the hermetic Immich v3 service."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

import httpx
import pytest

from immich_memories.analysis.duplicate_hashing import compute_thumbnail_hash, hamming_distance
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.generated_asset_tags import GENERATED_MEMORY_TAG
from immich_memories.api.immich import ImmichAuthError, SyncImmichClient
from immich_memories.api.models import Asset, AssetType
from immich_memories.generate_clips import MIN_CLIP_DURATION, assets_to_clips
from immich_memories.timeperiod import calendar_year
from tests.e2e import fake_immich
from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import CAST, LIBRARY, PARTNER_PICTURES

pytestmark = pytest.mark.e2e

_VIDEO_IDS = [p.asset_id for p in LIBRARY if p.is_video]
_PHOTO_IDS = [p.asset_id for p in LIBRARY if not p.is_video]
_VIDEO_SECONDS = [p.seconds for p in LIBRARY if p.is_video]
_JUNE_START = date(2024, 6, 1)
_JUNE_END = date(2024, 6, 30)


def _bucket_assets(server: FakeImmichServer, **params: str) -> list[Asset]:
    """One month bucket's assets, read straight off the fake's timeline endpoint."""
    response = httpx.get(
        f"{server.base_url}/api/timeline/bucket",
        params={"timeBucket": "2024-06-01T00:00:00.000Z", **params},
        headers={"x-api-key": server.api_key},
    )
    response.raise_for_status()
    return [Asset(**row) for row in response.json()]


def _probe_video(path: Path) -> dict:
    result = subprocess.run(  # noqa: S603
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height,pix_fmt,color_transfer",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _probe_image(path: Path) -> dict:
    result = subprocess.run(  # noqa: S603
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _upload_to_fake(server: FakeImmichServer, index: int) -> str:
    with server.source_video.open("rb") as source:
        response = httpx.post(
            f"{server.base_url}/api/assets",
            headers={"x-api-key": server.api_key},
            data={
                "filename": f"memory-{index}.mp4",
                "fileCreatedAt": "2024-06-01T12:00:00.000Z",
                "fileModifiedAt": "2024-06-01T12:00:00.000Z",
            },
            files={"assetData": (f"memory-{index}.mp4", source, "video/mp4")},
        )
    response.raise_for_status()
    return response.json()["id"]


def test_auto_client_detects_immich_v3_1(fake_immich_server) -> None:
    """The real client resolves the fake's advertised v3 server version."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="auto",
    ) as client:
        assert client.get_server_info().version_string == "3.1.0"
        assert client.get_api_version() is ResolvedApiVersion.V3


def test_current_user_uses_api_key_authentication(fake_immich_server) -> None:
    """The real client authenticates and receives the deterministic test user."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="auto",
    ) as client:
        user = client.get_current_user()

    assert user.id == "fake-user"
    assert user.email == "fake@example.test"
    assert user.name == "Fake Immich User"


def test_step1_connection_chain_returns_user_people_and_available_years(
    fake_immich_server,
) -> None:
    """The real Step 1 connection call chain completes against the fake."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="auto",
    ) as client:
        user = client.get_current_user()
        people = client.get_all_people()
        years = client.get_available_years()

    assert user.name == "Fake Immich User"
    assert [(person.id, person.name, person.is_hidden) for person in people] == [
        (f"person-{name.lower()}", name, False) for name in CAST
    ]
    assert years == [2024]


def test_wrong_api_key_is_rejected(fake_immich_server) -> None:
    """The fake catches browser tests that forgot or corrupted the API key."""
    # WHY: nothing is replaced here — the real client speaks to the in-process fake Immich.
    with (
        SyncImmichClient(fake_immich_server.base_url, "wrong-key", api_version="v3") as client,
        pytest.raises(ImmichAuthError, match="Invalid API key"),
    ):
        client.get_current_user()


def test_monthly_timeline_contains_every_synthetic_moment(fake_immich_server) -> None:
    """Timeline discovery exposes the fake's complete deterministic inventory."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        buckets = client.get_time_buckets()
    assets = _bucket_assets(fake_immich_server)

    # One month holds the whole library.
    assert [(bucket.time_bucket, bucket.count) for bucket in buckets] == [
        ("2024-06-01T00:00:00.000Z", len(LIBRARY)),
    ]
    assert [asset.id for asset in assets if asset.type is AssetType.VIDEO] == _VIDEO_IDS
    assert [asset.id for asset in assets if asset.type is AssetType.IMAGE] == _PHOTO_IDS


def test_the_timeline_refuses_a_media_type_it_does_not_define(fake_immich_server) -> None:
    """Immich's timeline has no `type`: real Immich drops it silently, the fake refuses it."""
    response = httpx.get(
        f"{fake_immich_server.base_url}/api/timeline/buckets",
        params={"type": "VIDEO"},
        headers={"x-api-key": fake_immich_server.api_key},
    )
    refused = list(fake_immich_server.refused)
    fake_immich_server.refused.clear()

    assert response.status_code == 400
    assert refused == ["GET /api/timeline/buckets: type is not a parameter Immich defines"]


def test_metadata_search_filters_the_video_and_photo_inventories(fake_immich_server) -> None:
    """The real search client receives exactly the requested media type."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        videos = client.search_metadata(
            asset_type=AssetType.VIDEO, taken_after=_JUNE_START, taken_before=_JUNE_END
        ).all_assets
        photos = client.search_metadata(
            asset_type=AssetType.IMAGE, taken_after=_JUNE_START, taken_before=_JUNE_END
        ).all_assets
        everything = client.search_metadata().all_assets

    assert len(everything) == len(LIBRARY)
    assert [asset.id for asset in videos] == _VIDEO_IDS
    assert [asset.duration_seconds for asset in videos] == _VIDEO_SECONDS
    assert [asset.id for asset in photos] == _PHOTO_IDS
    assert [asset.duration_seconds for asset in photos] == [None] * len(_PHOTO_IDS)


def test_metadata_search_narrows_to_the_named_faces(fake_immich_server) -> None:
    """A person filter is a server-side narrowing, the way Immich answers it."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        kit = client.search_metadata(person_ids=["person-kit"]).all_assets
        both = client.search_metadata(person_ids=["person-kit", "person-robin"]).all_assets

    assert {asset.id for asset in kit} == {p.asset_id for p in LIBRARY if "Kit" in p.people}
    assert {asset.id for asset in both} == {
        p.asset_id for p in LIBRARY if {"Kit", "Robin"} <= set(p.people)
    }
    assert 0 < len(both) < len(kit) < len(LIBRARY)


def test_search_statistics_counts_what_the_metadata_search_would_return(
    fake_immich_server,
) -> None:
    """The count honours every person (AND) and the taken-at window, and returns no assets."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        kit = client.count_assets_with_people(["person-kit"])
        both = client.count_assets_with_people(["person-kit", "person-robin"])
        in_the_distant_past = client.count_assets_with_people(
            ["person-kit"], taken_before=datetime(1990, 1, 1)
        )

    assert kit == sum("Kit" in p.people for p in LIBRARY)
    assert both == sum({"Kit", "Robin"} <= set(p.people) for p in LIBRARY)
    assert in_the_distant_past == 0


def test_search_uses_v3_millisecond_duration_on_the_wire(fake_immich_server) -> None:
    """The fake rejects accidental regression to Immich v2 duration strings."""
    response = httpx.post(
        f"{fake_immich_server.base_url}/api/search/metadata",
        headers={"x-api-key": fake_immich_server.api_key},
        json={
            "type": "VIDEO",
            "takenAfter": "2024-06-01T00:00:00.000Z",
            "takenBefore": "2024-06-30T23:59:59.999Z",
        },
    )

    response.raise_for_status()
    durations = [asset["duration"] for asset in response.json()["assets"]["items"]]
    assert durations == [int(seconds * 1000) for seconds in _VIDEO_SECONDS]
    assert all(type(duration) is int for duration in durations)


def test_the_generate_clip_conversion_keeps_every_fake_video(fake_immich_server) -> None:
    """The fake videos all become clips the way `generate` converts them, each long enough to cut."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        assets = client.get_videos_for_date_range(calendar_year(2024))

    clips = assets_to_clips(assets, min_duration=0.0)

    assert [clip.asset.id for clip in clips] == _VIDEO_IDS
    assert all(clip.duration_seconds >= MIN_CLIP_DURATION for clip in clips)


def test_original_and_playback_downloads_are_valid_h264_sdr_media(
    fake_immich_server,
    tmp_path: Path,
) -> None:
    """Both real download paths yield the generated, probeable source video."""
    assert fake_immich_server.source_video.is_relative_to(fake_immich_server.root)

    original_path = tmp_path / "original.mp4"
    playback_path = tmp_path / "playback.mp4"
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        client.download_asset(_VIDEO_IDS[0], original_path)
        playback_path.write_bytes(client.get_video_playback(_VIDEO_IDS[0]))

    for path in (original_path, playback_path):
        probe = _probe_video(path)
        streams = {stream["codec_type"]: stream for stream in probe["streams"]}
        assert streams["video"] == {
            "codec_name": "h264",
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "color_transfer": "bt709",
        }
        assert streams["audio"]["codec_name"] == "aac"
        assert float(probe["format"]["duration"]) == pytest.approx(_VIDEO_SECONDS[0], abs=0.1)


def test_photo_originals_are_generated_jpegs(fake_immich_server, tmp_path: Path) -> None:
    """Every fake photo downloads as a real JPEG above the source-quality floor."""
    # Both accounts' photos, and the edited render of each photo edited in Immich's editor.
    served = [p for p in (*LIBRARY, *PARTNER_PICTURES) if not p.is_video]
    edits = [p.asset_id + fake_immich.EDITED for p in served if p.edited]
    assert set(fake_immich_server.photo_paths) == {p.asset_id for p in served} | set(edits)
    assert all(
        path.is_relative_to(fake_immich_server.root)
        for path in fake_immich_server.photo_paths.values()
    )

    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        downloaded = {
            picture: client.download_asset(picture.asset_id, tmp_path / f"{picture.asset_id}.jpg")
            for picture in LIBRARY
            if not picture.is_video
        }

    for picture, path in downloaded.items():
        # A portrait photo is the same size, stood on its end.
        width, height = (1280, 1920) if picture.portrait else (1920, 1280)
        assert _probe_image(path)["streams"] == [
            {"codec_name": "mjpeg", "codec_type": "video", "width": width, "height": height}
        ]


def test_every_asset_thumbnail_shows_its_own_scene(fake_immich_server) -> None:
    """One preview served for every asset made Phase 1 collapse the pool (#525)."""
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="v3",
    ) as client:
        hashes = {
            asset_id: compute_thumbnail_hash(client.get_asset_thumbnail(asset_id, size="preview"))
            for asset_id in _VIDEO_IDS + _PHOTO_IDS
        }

    # The editor's duplicate gate: a thumbnail pair within 8 hash bits reads as one scene.
    # The library carries near-duplicate frames on purpose (the phone's second shot of
    # the same moment), so a few close pairs are expected; one preview shared by all
    # assets, the #525 regression, would collapse every pair to zero.
    threshold = 8
    distances = {
        (left, right): hamming_distance(hashes[left], hashes[right])
        for left, right in combinations(sorted(hashes), 2)
    }
    assert all(hashes.values())
    # Assets made from one photograph share its preview: the Live Photo stills are drawn from
    # library pictures (the window where nothing moves, and the three takes of one kick).
    # Every other asset has its own.
    sources = {(p.source, p.is_video) for p in LIBRARY}
    assert len(set(hashes.values())) == len(sources), "two pictures share one preview"
    close = {pair: d for pair, d in distances.items() if d <= threshold}
    assert len(close) < 0.02 * len(distances), f"near-duplicate previews: {close}"


def test_real_auto_client_uploads_and_fake_records_v3_multipart(fake_immich_server) -> None:
    """A real v3 upload is accepted and retained for launch-smoke assertions."""
    # The session's service may hold uploads from tests that ran before this one.
    before = len(fake_immich_server.uploads)
    with SyncImmichClient(
        fake_immich_server.base_url,
        fake_immich_server.api_key,
        api_version="auto",
    ) as client:
        asset_id = client.upload_asset(fake_immich_server.source_video)

    assert asset_id == f"uploaded-{before + 1}"
    assert len(fake_immich_server.uploads) == before + 1
    upload = fake_immich_server.uploads[before]
    assert set(upload.fields) == {"filename", "fileCreatedAt", "fileModifiedAt"}
    source_name = fake_immich_server.source_video.name
    assert upload.fields["filename"] == source_name
    assert upload.filename == source_name
    assert upload.content_type == "video/mp4"
    assert upload.data == fake_immich_server.source_video.read_bytes()


def test_concurrent_uploads_receive_unique_ids_and_are_all_recorded(tmp_path: Path) -> None:
    """Concurrent handler threads allocate one unique ID per recorded upload."""
    server = FakeImmichServer.start(tmp_path / "concurrent", upload_commit_delay=0.02)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            asset_ids = list(pool.map(lambda index: _upload_to_fake(server, index), range(6)))
    finally:
        server.close()

    assert set(asset_ids) == {f"uploaded-{index}" for index in range(1, 7)}
    assert len(server.uploads) == 6
    assert len({upload.filename for upload in server.uploads}) == 6


@pytest.mark.parametrize("v2_field", ["deviceAssetId", "deviceId"])
def test_v3_upload_rejects_each_v2_device_field(fake_immich_server, v2_field: str) -> None:
    """Each removed v2 identity field makes the v3 multipart request invalid."""
    upload_count = len(fake_immich_server.uploads)
    with fake_immich_server.source_video.open("rb") as source:
        response = httpx.post(
            f"{fake_immich_server.base_url}/api/assets",
            headers={"x-api-key": fake_immich_server.api_key},
            data={
                "filename": "memory.mp4",
                "fileCreatedAt": "2024-06-01T12:00:00.000Z",
                "fileModifiedAt": "2024-06-01T12:00:00.000Z",
                v2_field: "removed-in-v3",
            },
            files={"assetData": ("memory.mp4", source, "video/mp4")},
        )

    assert response.status_code == 400
    assert response.json() == {"message": f"v3 upload rejects {v2_field}"}
    assert len(fake_immich_server.uploads) == upload_count


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_unexpected_method_endpoint_pairs_return_json_diagnostics(
    fake_immich_server,
    method: str,
) -> None:
    """Unimplemented smoke traffic fails loudly with its exact request pair."""
    response = httpx.request(
        method,
        f"{fake_immich_server.base_url}/api/not-implemented",
        headers={"x-api-key": fake_immich_server.api_key},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": "unexpected fake Immich request",
        "method": method,
        "path": "/api/not-implemented",
    }


def test_the_library_can_be_served_on_every_interface(tmp_path: Path) -> None:
    """The setup matrix serves this library to a NAS and a cluster over the LAN.

    Binding a wildcard is the whole change. It is asserted here rather than in
    the matrix tests because the contract belongs to this service: an address it
    hands back must be one a caller can fetch, and every asset URL it serves must
    stay relative so the host it was reached on is the host the client keeps using.
    """
    server = FakeImmichServer.start(tmp_path / "lan", host="0.0.0.0", port=0)  # noqa: S104
    try:
        assert server.base_url.startswith("http://127.0.0.1:")
        assert server.listening_host == "0.0.0.0", "a loopback bind never reaches the NAS"  # noqa: S104

        version = httpx.get(
            f"{server.base_url}/api/server/version", headers={"x-api-key": server.api_key}
        )
        assert version.status_code == 200
        thumbnail = httpx.get(
            f"{server.base_url}/api/assets/{_PHOTO_IDS[0]}/thumbnail",
            headers={"x-api-key": server.api_key},
        )
        assert thumbnail.status_code == 200
    finally:
        server.close()


def test_serving_the_same_root_twice_reuses_its_media_directory(
    monkeypatch, tmp_path: Path
) -> None:
    """The setup matrix runs one lane per invocation into the same output directory.

    The second invocation serves the same library out of the same root, and used
    to die on `thumbnails/` already existing before it had bound anything.
    """
    # WHY: replaces the ffmpeg renders. This is about the directory the service
    # lays out, and rendering the whole library twice buys the assertion nothing.
    monkeypatch.setattr(fake_immich, "_ffmpeg", lambda *_args: None)
    # The HDR photo's gain map is added to the JPEG FFmpeg would have rendered.
    monkeypatch.setattr(fake_immich, "_add_gain_map", lambda _photo: None)
    root = tmp_path / "served-twice"

    for _ in range(2):
        server = FakeImmichServer.start(root)
        server.close()

    assert (root / "media" / "thumbnails").is_dir()


def test_source_discovery_can_exclude_generated_films(fake_immich_server):
    with SyncImmichClient(
        base_url=fake_immich_server.base_url,
        api_key=fake_immich_server.api_key,
        api_version="auto",
    ) as client:
        assert client.generated_asset_ids() == frozenset()


def test_a_service_on_borrowed_media_starts_empty_and_answers_tag_searches(
    fake_immich_server, tmp_path: Path
):
    """A second service on the first one's media holds none of its uploads or tags.

    Its tag search answers what Immich does: only the assets under the tag. Ignoring
    `tagIds` would make every library picture one of the app's own films.
    """
    server = FakeImmichServer.start(tmp_path / "own", media_of=fake_immich_server)
    try:
        with SyncImmichClient(server.base_url, server.api_key, api_version="auto") as client:
            untagged = client.generated_asset_ids()
            asset_id = client.upload_asset(server.source_video)
        headers = {"x-api-key": server.api_key}
        tags = httpx.put(
            f"{server.base_url}/api/tags", json={"tags": [GENERATED_MEMORY_TAG]}, headers=headers
        ).json()
        httpx.put(
            f"{server.base_url}/api/tags/{tags[0]['id']}/assets",
            json={"ids": [asset_id]},
            headers=headers,
        )
        found = httpx.post(
            f"{server.base_url}/api/search/metadata",
            json={"tagIds": [tags[0]["id"]], "size": 250, "page": 1},
            headers=headers,
        ).json()["assets"]["items"]
    finally:
        server.close()

    assert server.photo_paths == fake_immich_server.photo_paths
    assert untagged == frozenset()
    assert asset_id == "uploaded-1"
    assert [asset["id"] for asset in found] == [asset_id]
    assert server.refused == []
