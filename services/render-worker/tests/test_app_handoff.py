"""The app and worker agree on the cut at their HTTP boundary."""

from uuid import uuid4


def manual_params(tmp_path):
    from immich_memories.api.models import Asset, VideoClipInfo
    from immich_memories.config import Config
    from immich_memories.generate import GenerationParams

    asset = Asset(
        id=str(uuid4()),
        type="VIDEO",
        originalFileName="source.mp4",
        fileCreatedAt="2026-01-01T12:00:00Z",
        fileModifiedAt="2026-01-01T12:00:00Z",
        updatedAt="2026-01-01T12:00:00Z",
        duration="00:00:10",
    )
    config = Config()
    config.immich.url = "http://immich.invalid"
    config.immich.api_key = "test-scoped-key"
    config.title_screens.enabled = False
    return GenerationParams(
        clips=[VideoClipInfo(asset=asset, duration_seconds=10, width=1920, height=1080)],
        output_path=tmp_path / "film.mp4",
        config=config,
        target_duration_seconds=30,
        output_orientation="square",
        output_resolution="720p",
        clip_segments={asset.id: (2.5, 5.75)},
        memory_key_override="manual-cut",
    )


def round_trip(params, tmp_path, *, geocoding_url=None):
    import httpx
    from immich_memories_render_worker.admission import certify_envelope
    from immich_memories_render_worker.models import RenderRequest
    from immich_memories_render_worker.native_plan import generation_params

    from immich_memories.processing.remote_render_plan import build_render_request

    body = build_render_request(params)
    # Exercise the same JSON encoder as RemoteRenderClient's POST /jobs.
    wire = httpx.Request("POST", "http://render.invalid/jobs", json=body)
    request = RenderRequest.model_validate_json(wire.content)
    certify_envelope(request)

    class Client:
        def get_asset(self, asset_id):
            return next(clip.asset for clip in params.clips if clip.asset.id == asset_id)

    # WHY: this contract round trip needs the source metadata, not a running Immich server.
    received = generation_params(
        request, tmp_path / "worker", Client(), lambda *_: None, geocoding_url=geocoding_url
    )
    return received, body


def test_app_envelope_preserves_manual_cut_and_square_canvas(tmp_path):
    params = manual_params(tmp_path)
    asset = params.clips[0].asset
    received, body = round_trip(params, tmp_path)
    assert [clip.asset.id for clip in received.clips] == [asset.id]
    assert received.clip_segments == {asset.id: (2.5, 5.75)}
    assert received.output_orientation == "square"
    assert received.output_resolution == "720p"
    assert received.target_duration_seconds == 30
    assert received.editorial_render_timing == body["timing"]
    assert body["memory"]["date_start"] is None
    assert body["memory"]["date_end"] is None


def test_trip_calendar_bounds_survive_http_json_and_worker_title_generation(tmp_path):
    from datetime import date

    from immich_memories.generate_privacy import generate_trip_title_text

    params = manual_params(tmp_path)
    params.memory_type = "trip"
    params.date_start = date(2024, 2, 29)
    params.date_end = date(2024, 3, 3)
    params.memory_preset_params = {
        "location_name": "Example City",
        "location_kind": "city",
        "trip_start": params.date_start,
        "trip_end": params.date_end,
        "home_lat": 40.0,
        "home_lon": -70.0,
    }
    original = params.memory_preset_params.copy()
    received, body = round_trip(params, tmp_path)
    assert body["memory"]["preset_params"] == original | {
        "trip_start": "2024-02-29",
        "trip_end": "2024-03-03",
    }
    assert params.memory_preset_params == original
    assert received.memory_preset_params == original
    assert received.date_start == params.date_start
    assert received.date_end == params.date_end
    assert received.editorial_render_timing == body["timing"]
    assert generate_trip_title_text(received.memory_preset_params) == generate_trip_title_text(
        original
    )


def test_worker_rejects_invalid_trip_calendar_bounds():
    import pytest
    from immich_memories_render_worker.models import MemorySettings
    from pydantic import ValidationError

    for value in ("2024-02-30", 20240229, ["2024-02-29"]):
        with pytest.raises(ValidationError, match="trip_start"):
            MemorySettings(target_duration_seconds=30, preset_params={"trip_start": value})


def test_trip_map_timeline_survives_the_http_worker_handoff(tmp_path):
    from datetime import date

    from immich_memories.api.models import ExifInfo, VideoClipInfo
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.processing.remote_render import _expected_duration, _map_extra

    params = manual_params(tmp_path)
    params.memory_type = "trip"
    params.config.title_screens.enabled = True
    params.config.network.map_tiles = True
    params.memory_preset_params = {
        "location_name": "Example Trip",
        "trip_start": date(2024, 2, 1),
        "trip_end": date(2024, 2, 2),
        "home_lat": 40.0,
        "home_lon": -70.0,
    }
    params.clips[0].asset.exif_info = ExifInfo(latitude=48.0, longitude=2.0, city="First Town")
    second = params.clips[0].asset.model_copy(
        update={
            "id": str(uuid4()),
            "file_created_at": params.clips[0].asset.file_created_at.replace(day=2),
            "exif_info": ExifInfo(latitude=49.0, longitude=3.0, city="Second Town"),
        }
    )
    params.clips.append(VideoClipInfo(asset=second, duration_seconds=10, width=1920, height=1080))
    params.clip_segments[second.id] = (2.5, 5.75)
    received, body = round_trip(params, tmp_path)
    content = [
        AssemblyClip(
            path=tmp_path / f"source-{index}.mp4",
            asset_id=clip.asset.id,
            duration=3.25,
            date=clip.asset.file_created_at.isoformat(),
            latitude=clip.asset.exif_info.latitude,
            longitude=clip.asset.exif_info.longitude,
            location_name=clip.asset.exif_info.city,
        )
        for index, clip in enumerate(params.clips)
    ]
    assert _map_extra(params, body, content) > 0
    assert _expected_duration(received, body, content) == _expected_duration(params, body, content)
    assert _map_extra(received, body, content) == _map_extra(params, body, content)


def test_an_editorial_directive_keeps_its_cut_without_a_manual_segment_map(tmp_path):
    from immich_memories.analysis.editorial_planner import EditorialSelection

    params = manual_params(tmp_path)
    asset_id = params.clips[0].asset.id
    params.clip_segments = {}
    params.editorial_selections = (EditorialSelection(asset_id, 2.5, 5.75, "motion"),)
    received, _ = round_trip(params, tmp_path)
    assert received.clip_segments == {asset_id: (2.5, 5.75)}


def test_a_directive_with_omitted_bounds_uses_the_full_source(tmp_path):
    from immich_memories.analysis.editorial_planner import EditorialSelection

    params = manual_params(tmp_path)
    asset_id = params.clips[0].asset.id
    params.clip_segments = {}
    params.editorial_selections = (EditorialSelection(asset_id, None, None, None),)
    received, _ = round_trip(params, tmp_path)
    assert received.clip_segments == {asset_id: (0, 10)}


def test_remote_render_retains_film_settings_and_source_audio_markers(tmp_path):
    from immich_memories.processing.encoding_plan import HdrMode

    params = manual_params(tmp_path)
    params.config.title_screens.enabled = True
    params.config.title_screens.animated_background = False
    params.config.title_screens.use_first_name_only = False
    params.config.network.geocoding = True
    params.config.network.geocoding_url = "http://geocoder.invalid:8080"
    params.config.network.map_tiles = True
    params.config.output.hdr_mode = HdrMode.AUTO
    params.config.output.quality = "fast"
    params.config.photos.duration = 2.5
    params.scale_mode = "fit"
    params.add_date_overlay = True
    params.add_place_overlay = True
    params.privacy_mode = True
    params.person_name = "Example Person"
    params.memory_preset_params = {"birthday_age": 10}
    clip = params.clips[0]
    clip.audio_categories = ["speech", "music"]
    clip.llm_emotion = "happy"
    params.clip_rotations = {clip.asset.id: 90}

    received, _ = round_trip(params, tmp_path, geocoding_url="http://geocoder.invalid:8080")
    assert received.config.title_screens == params.config.title_screens
    assert received.config.network == params.config.network
    assert received.config.photos.duration == 2.5
    assert received.config.output.hdr_mode == HdrMode.AUTO
    assert received.config.output.quality == "fast"
    assert received.scale_mode == "fit"
    assert received.add_date_overlay and received.add_place_overlay and received.privacy_mode
    assert received.person_name == params.person_name
    assert received.memory_preset_params == params.memory_preset_params
    assert received.clip_rotations == params.clip_rotations
    assert received.clips[0].audio_categories == ["speech", "music"]
    assert received.clips[0].llm_emotion == "happy"


def test_the_worker_geocodes_only_through_its_own_configured_server(tmp_path):
    params = manual_params(tmp_path)
    params.config.network.geocoding = True
    params.config.network.geocoding_url = "http://evil.invalid"

    received, body = round_trip(params, tmp_path, geocoding_url="http://nominatim.worker:8080")

    assert body["network"]["geocoding_url"] == "http://evil.invalid"
    assert received.config.network.geocoding
    assert received.config.network.geocoding_url == "http://nominatim.worker:8080"


def test_a_worker_without_a_geocoding_server_never_geocodes(tmp_path):
    params = manual_params(tmp_path)
    params.config.network.geocoding = True
    params.config.network.geocoding_url = "http://evil.invalid"

    received, _ = round_trip(params, tmp_path)

    assert not received.config.network.geocoding
    assert received.config.network.geocoding_url == ""


def test_the_worker_reads_its_geocoding_server_from_its_own_environment(monkeypatch, tmp_path):
    from immich_memories_render_worker.settings import WorkerSettings

    monkeypatch.setenv("IMMICH_MEMORIES_RENDER_WORKER_GEOCODING_URL", "http://nominatim.lan:8080")
    settings = WorkerSettings(token="t" * 32, immich_url="http://immich.invalid", directory=tmp_path)

    assert settings.geocoding_url == "http://nominatim.lan:8080"
    assert WorkerSettings(
        token="t" * 32, immich_url="http://immich.invalid", directory=tmp_path, geocoding_url=None
    ).geocoding_url is None


def test_an_explicit_hevc_output_is_still_hevc_on_the_worker(tmp_path):
    from immich_memories.processing.encoding_plan import resolve_output_selection

    params = manual_params(tmp_path)
    params.output_format = "h265"
    received, body = round_trip(params, tmp_path)
    assert body["output"]["codec"] == "h265"
    selected = resolve_output_selection(
        config_codec=received.config.output.codec,
        config_container=received.config.output.format,
        format_override=received.output_format,
    )
    assert selected.codec.value == "h265"


def test_manual_photo_without_a_video_duration_uses_its_chosen_hold(tmp_path):
    from immich_memories.api.models import AssetType

    params = manual_params(tmp_path)
    params.clips[0].asset.type = AssetType.IMAGE
    params.clips[0].duration_seconds = 0
    params.clip_segments = {}
    params.target_duration_seconds = None
    params.config.photos.duration = 2.5
    received, body = round_trip(params, tmp_path)
    assert body["plan"]["clips"][0]["render_mode"] == "still"
    assert received.clip_segments == {params.clips[0].asset.id: (0, 2.5)}


def test_the_workers_place_captions_use_the_apps_home_location(tmp_path):
    params = manual_params(tmp_path)
    params.add_place_overlay = True
    params.config.trips.homebase_latitude = 40.0
    params.config.trips.homebase_longitude = -70.0
    received, _ = round_trip(params, tmp_path)
    assert received.config.trips.homebase_latitude == 40.0
    assert received.config.trips.homebase_longitude == -70.0


def test_a_manually_selected_live_carrier_keeps_motion_and_its_stitched_duration(tmp_path):
    from immich_memories_render_worker.models import RenderRequest
    from immich_memories_render_worker.native_plan import generation_params
    from test_live_contract import LiveAssets, live_body

    body, material = live_body()
    params = generation_params(
        RenderRequest.model_validate(body), tmp_path, LiveAssets(material), lambda *_: None
    )
    params.clips[0].editorial_live_manifest = None
    params.editorial_render_timing = None
    params.editorial_selections = ()
    received, envelope = round_trip(params, tmp_path)
    chosen = envelope["plan"]["clips"][0]
    assert chosen["render_mode"] == "motion"
    assert chosen["live"]["material"] == material.as_dict()
    assert received.clips[0].duration_seconds == material.duration_seconds
    assert chosen["live"]["selected_interval"] == [0.5, 2.5]


def test_monthly_preset_datetime_bounds_round_trip_as_calendar_dates(tmp_path):
    from datetime import date

    from immich_memories.memory_types.date_builders import build_month

    params = manual_params(tmp_path)
    period = build_month(2, 2024)
    params.date_start = period.start
    params.date_end = period.end
    params.memory_type = "monthly_highlights"
    params.memory_key_override = None
    from immich_memories.generate import build_memory_key

    expected_key = build_memory_key(params)
    received, body = round_trip(params, tmp_path)
    assert body["memory"]["date_start"] == "2024-02-01"
    assert body["memory"]["date_end"] == "2024-02-29"
    assert received.date_start == date(2024, 2, 1)
    assert received.date_end == date(2024, 2, 29)
    assert body["memory_key"] == expected_key
    assert received.editorial_render_timing == body["timing"]

    params.date_start = period.start.date()
    params.date_end = period.end.date()
    _, plain_dates = round_trip(params, tmp_path)
    assert plain_dates["memory"] == body["memory"]
    assert plain_dates["timing"] == body["timing"]
    assert plain_dates["memory_key"] == build_memory_key(params)


def test_remote_dates_keep_the_presets_local_calendar_day(tmp_path):
    from datetime import datetime, timedelta, timezone

    params = manual_params(tmp_path)
    params.date_start = datetime(2024, 2, 1, 0, 30, tzinfo=timezone(timedelta(hours=14)))
    params.date_end = datetime(2024, 2, 29, 23, 59, tzinfo=timezone(timedelta(hours=-12)))
    _, body = round_trip(params, tmp_path)
    assert body["memory"]["date_start"] == "2024-02-01"
    assert body["memory"]["date_end"] == "2024-02-29"


def test_worker_still_refuses_timestamp_in_calendar_date_field(tmp_path):
    import pytest
    from immich_memories_render_worker.models import RenderRequest
    from pydantic import ValidationError

    from immich_memories.processing.remote_render_plan import build_render_request

    body = build_render_request(manual_params(tmp_path))
    body["memory"]["date_end"] = "2024-02-29T23:59:59"
    with pytest.raises(ValidationError) as error:
        RenderRequest.model_validate(body)
    assert error.value.errors()[0]["loc"] == ("memory", "date_end")
    assert error.value.errors()[0]["type"] == "date_from_datetime_inexact"


def test_privacy_trip_validation_uses_the_same_relocated_home_as_the_renderer(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    import pytest

    from immich_memories.generate import GenerationError
    from immich_memories.generate_privacy import anonymize_clips_for_privacy
    from immich_memories.generate_render import _anonymized_params
    from immich_memories.generate_settings import build_title_settings
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.processing.editorial_timing import read_editorial_timeline
    from immich_memories.processing.encoding_plan import OutputCodec
    from immich_memories.processing.remote_render import _map_extra, _validate_result
    from immich_memories.processing.timeline_preview import preview_map_extra, preview_timeline

    params = manual_params(tmp_path)
    params.memory_type = "trip"
    params.privacy_mode = True
    params.config.title_screens.enabled = True
    params.config.network.map_tiles = True
    params.config.network.geocoding = False
    params.memory_preset_params = {"home_lat": 40.0, "home_lon": -70.0}
    received, body = round_trip(params, tmp_path)
    content = anonymize_clips_for_privacy(
        [
            AssemblyClip(
                path=tmp_path / "source.mp4",
                asset_id=params.clips[0].asset.id,
                duration=3.25,
                latitude=48.0,
                longitude=2.0,
            )
        ]
    )
    timeline = read_editorial_timeline(body["timing"])
    worker_params = _anonymized_params(replace(received, timeline_plan=timeline))
    titles = build_title_settings(worker_params, worker_params.config, content)
    _, duration = preview_timeline(
        content, timeline, titles, params.transition, params.transition_duration
    )
    probe = SimpleNamespace(width=720, height=720, duration_seconds=duration)
    plan = SimpleNamespace(container="mp4", codec=OutputCodec.H264, hdr=False)
    _validate_result(params, body, {}, content, probe, plan)
    assert _map_extra(params, body, content) == preview_map_extra(content, timeline, titles)
    assert params.memory_preset_params == {"home_lat": 40.0, "home_lon": -70.0}
    probe.duration_seconds += 1
    with pytest.raises(GenerationError, match="film duration"):
        _validate_result(params, body, {}, content, probe, plan)
