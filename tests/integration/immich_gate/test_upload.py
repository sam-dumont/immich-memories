"""Real-Immich gate: a finished film goes back into Immich, into its album, on v2 and v3."""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.integration.immich_fixtures import requires_immich

pytestmark = [requires_immich]

_FILM_NAME = "gate_memory_0f1e2d3c.mp4"
_CAPTURED = datetime(2024, 6, 30, 12, 0, tzinfo=UTC)


def _render(folder: Path, colour: str) -> Path:
    """A one-second film; the colour makes each render a different file under the same name."""
    folder.mkdir(parents=True)
    film = folder / _FILM_NAME
    subprocess.run(  # noqa: S603 -- fixed argv
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:s=320x240:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            # Unique bytes per run: Immich answers a checksum it already holds
            # (even in the trash) with that old asset instead of a new upload.
            "-metadata",
            f"comment={uuid.uuid4()}",
            str(film),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return film


def _read_by_immich(gate_client, asset_id: str) -> bool:
    """Whether Immich's metadata job has read the file (only it sets dateTimeOriginal)."""
    for _ in range(60):
        exif = gate_client.get_asset(asset_id).exif_info
        if exif is not None and exif.date_time_original is not None:
            return True
        time.sleep(0.5)
    return False


@pytest.mark.feature("upload.film-into-album")
def test_a_rerendered_film_is_filed_in_its_album_and_replaces_the_earlier_one(
    gate_client, tmp_path
):
    album = f"Gate films {uuid.uuid4().hex[:8]}"
    first = gate_client.upload_memory(_render(tmp_path / "a", "red"), album, captured_at=_CAPTURED)
    # A real re-render comes long after Immich read the first upload. That read
    # used to wipe a tag applied while it ran (#1270), so the film lost its
    # provenance and a v3 re-render kept it as a duplicate.
    assert _read_by_immich(gate_client, first["asset_id"])
    assert first["asset_id"] in gate_client.generated_asset_ids()
    second = gate_client.upload_memory(
        _render(tmp_path / "b", "blue"), album, captured_at=_CAPTURED
    )

    assert first["album_id"] is not None
    assert second["album_id"] == first["album_id"]
    assert gate_client.resolve_album(album).id == first["album_id"]
    assert gate_client.get_asset(second["asset_id"]).file_created_at == _CAPTURED

    filed = sorted(
        asset["id"]
        for asset in gate_client.list_album_assets(second["album_id"])
        if asset.get("originalFileName") == _FILM_NAME
    )
    # v2 proves the earlier render is ours by its device identity; v3 dropped
    # deviceId, so there the immich-memories/generated tag proves it. Either way
    # the earlier render of the same recipe goes to Immich's trash.
    assert filed == [second["asset_id"]]
    assert gate_client.get_asset(first["asset_id"]).is_trashed


@pytest.mark.feature("upload.film-description-and-tags")
def test_a_film_keeps_its_description_and_tags_after_immich_reads_it(gate_client, tmp_path):
    import httpx

    from immich_memories.api.film_label import FilmLabel

    label = FilmLabel(
        description="July 2025 · Kit's birthday, then The road north",
        tags=(
            "immich-memories/type/Monthly highlights",
            "immich-memories/year/2025",
            "immich-memories/story/Kit's birthday",
        ),
    )
    answer = gate_client.upload_memory(
        _render(tmp_path / "label", "green"), None, captured_at=_CAPTURED, label=label
    )
    with httpx.Client(
        base_url=f"{gate_client.base_url}/api",
        headers={"x-api-key": gate_client.api_key},
        timeout=30,
    ) as admin:
        try:
            asset = admin.get(f"/assets/{answer['asset_id']}").raise_for_status().json()
        finally:
            admin.request(
                "DELETE", "/assets", json={"ids": [answer["asset_id"]], "force": True}
            ).raise_for_status()

    assert answer["warnings"] == []
    assert asset["exifInfo"]["description"] == label.description
    assert {tag["value"] for tag in asset["tags"]} == {"immich-memories/generated", *label.tags}


@dataclass
class _Clip:
    """The streaming assembler's duck-typed clip."""

    path: Path
    duration: float
    is_title_screen: bool = False
    rotation_override: int | None = None
    is_hdr: bool = False
    color_transfer: str | None = None
    input_seek: float = 0.0


@pytest.mark.feature("upload.film-dated-by-last-picture")
def test_immich_files_a_rendered_film_by_its_own_capture_tags(
    gate_client, test_clip_720p, test_music_short, tmp_path
):
    """Rendered and mixed with this machine's FFmpeg, uploaded with no date of its own."""
    from immich_memories.audio.mixer import DuckingConfig, MixConfig, mix_audio_with_ducking
    from immich_memories.processing.streaming_assembler import streaming_assemble_full

    captured_at = datetime(2023, 8, 14, 21, 30, tzinfo=timezone(timedelta(hours=2)))
    rendered = tmp_path / "rendered.mp4"
    streaming_assemble_full(
        clips=[_Clip(test_clip_720p, 2.0)],
        transitions=[],
        output_path=rendered,
        width=1280,
        height=720,
        fps=30,
        captured_at=captured_at,
    )
    film = tmp_path / f"gate_dated_{uuid.uuid4().hex[:8]}.mp4"
    fades = MixConfig(ducking=DuckingConfig(), fade_in_seconds=0.2, fade_out_seconds=0.2)
    mix_audio_with_ducking(rendered, test_music_short, film, fades)

    import httpx

    # No upload date: only the file's own tags can file it on its day.
    answer = gate_client.upload_memory(film, None, captured_at=None)
    with httpx.Client(
        base_url=f"{gate_client.base_url}/api",
        headers={"x-api-key": gate_client.api_key},
        timeout=30,
    ) as admin:
        try:
            assert _read_by_immich(gate_client, answer["asset_id"])
            asset = admin.get(f"/assets/{answer['asset_id']}").raise_for_status().json()
        finally:
            admin.request(
                "DELETE", "/assets", json={"ids": [answer["asset_id"]], "force": True}
            ).raise_for_status()

    filed_at = datetime(2023, 8, 14, 19, 30, tzinfo=UTC)
    assert datetime.fromisoformat(asset["exifInfo"]["dateTimeOriginal"]) == filed_at
    assert datetime.fromisoformat(asset["fileCreatedAt"]) == filed_at
    assert asset["localDateTime"].startswith("2023-08-14T21:30:00")
    assert asset["exifInfo"]["timeZone"] == "UTC+2"
