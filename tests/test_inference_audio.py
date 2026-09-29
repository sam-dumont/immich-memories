"""The owned inference service separates audio without a MusicGen server."""

from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient

from immich_memories.audio.music_generator_models import MusicStems
from immich_memories_inference.app import create_app
from immich_memories_inference.settings import InferenceSettings


class SyntheticSeparator:
    """Replace model inference with deterministic stem files at its write boundary."""

    async def separate_stems(self, audio_path, output_dir, progress_callback=None):
        paths = {}
        for name in ("drums", "bass", "other", "vocals"):
            paths[name] = output_dir / f"{name}.wav"
            paths[name].write_bytes(audio_path.read_bytes())
        return MusicStems(**paths)


def test_inference_returns_four_stems(tmp_path):
    # WHY: replace the expensive model, keeping HTTP, upload and archive handling real.
    app = create_app(InferenceSettings(cache_dir=tmp_path), audio_separator=SyntheticSeparator())
    with TestClient(app) as client:
        response = client.post("/audio/stems", files={"file": ("input.wav", b"synthetic")})
        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {"drums.wav", "bass.wav", "other.wav", "vocals.wav"}
            assert archive.read("other.wav") == b"synthetic"
        assert client.get("/ping").status_code == 200
    assert not list(tmp_path.glob("demucs-*"))


@pytest.mark.asyncio
async def test_app_downloads_the_inference_stems(tmp_path, monkeypatch):
    from immich_memories.audio.generators.inference_demucs import InferenceDemucs

    # WHY: model output is synthetic; the HTTP client talks to the actual ASGI app.
    app = create_app(InferenceSettings(cache_dir=tmp_path), audio_separator=SyntheticSeparator())
    client_type = httpx.AsyncClient
    # WHY: replace only the network connection with the service's in-process HTTP transport.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_type(**kw, transport=httpx.ASGITransport(app=app))
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic")
    result = await InferenceDemucs("http://inference").separate_stems(source, tmp_path / "out")
    assert result.has_full_stems
    assert result.other.read_bytes() == b"synthetic"


@pytest.mark.asyncio
async def test_pipeline_uses_configured_inference_for_stems(tmp_path, monkeypatch):
    from immich_memories.audio.music_generator_models import VideoTimeline
    from immich_memories.audio.music_pipeline import create_pipeline
    from immich_memories.config_loader import Config
    from tests.test_music_pipeline import FakeGenerator

    # WHY: generation and separation models are external computation boundaries.
    app = create_app(InferenceSettings(cache_dir=tmp_path), audio_separator=SyntheticSeparator())
    monkeypatch.setattr(
        "immich_memories.audio.generators.factory.create_generator", lambda *_args: FakeGenerator()
    )
    client_type = httpx.AsyncClient
    # WHY: send the app's actual request to the inference HTTP service without a TCP listener.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_type(**kw, transport=httpx.ASGITransport(app=app))
    )
    config = Config()
    config.ace_step.enabled = True
    config.inference.facts_base_url = "http://inference"
    result = await create_pipeline(config).generate_music_for_video(
        VideoTimeline(), tmp_path, num_versions=1
    )
    assert result.versions[0].stems is not None
    assert result.versions[0].stems.has_full_stems


@pytest.mark.asyncio
async def test_unavailable_inference_uses_local_separator(tmp_path, monkeypatch):
    from immich_memories.audio.generators.inference_demucs import InferenceDemucs

    client_type = httpx.AsyncClient
    # WHY: the service outage is the external failure under test.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client_type(
            **kw, transport=httpx.MockTransport(lambda _request: httpx.Response(503))
        ),
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"local fallback")
    output = tmp_path / "out"
    output.mkdir()
    # WHY: replace local model inference; fallback must still produce actual stem files.
    result = await InferenceDemucs(
        "http://inference", fallback=SyntheticSeparator()
    ).separate_stems(source, output)
    assert result.other.read_bytes() == b"local fallback"


def test_failed_separation_cleans_uploaded_audio(tmp_path):
    class BrokenSeparator:
        async def separate_stems(self, *_args):
            raise RuntimeError("private input details")

    # WHY: exercise the HTTP failure boundary without loading a model.
    app = create_app(InferenceSettings(cache_dir=tmp_path), audio_separator=BrokenSeparator())
    with TestClient(app) as client:
        response = client.post("/audio/stems", files={"file": ("input.wav", b"audio")})
        assert response.status_code == 503
        assert "private input" not in response.text
        assert not list(tmp_path.glob("demucs-*"))
        assert client.post("/audio/stems", files={"file": ("empty.wav", b"")}).status_code == 400
