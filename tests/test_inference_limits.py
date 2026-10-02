"""The inference service bounds what one request can make it hold."""

from __future__ import annotations

import asyncio
import base64
import threading
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from immich_memories.audio.music_generator_models import MusicStems
from immich_memories_inference.app import create_app
from immich_memories_inference.producers import HEADS, Fact, ProducerFacts
from immich_memories_inference.runtime import ProducerRuntime
from immich_memories_inference.settings import InferenceSettings


class EchoHeads:
    """# WHY: stands in for the ONNX weights; only the HTTP limits are under test."""

    name = HEADS
    encoder_key = "a" * 64
    versions = {"people": "public-v1"}

    def decide(self, image: bytes) -> ProducerFacts:
        return ProducerFacts(
            producer=self.name,
            encoder_key=self.encoder_key,
            facts=(Fact(head="people", version="public-v1", label="yes", confidence=0.5),),
        )


class HeldSeparator:
    """# WHY: stands in for Demucs, holding until released so a second upload overlaps it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def separate_stems(self, audio_path, output_dir, progress_callback=None):
        self.calls += 1
        self.started.set()
        self.release.wait(10)
        paths = {}
        for name in ("drums", "bass", "other", "vocals"):
            paths[name] = output_dir / f"{name}.wav"
            paths[name].write_bytes(b"stem")
        return MusicStems(**paths)


def _app(tmp_path, separator=None, **settings):
    runtime = ProducerRuntime({HEADS: EchoHeads})
    return create_app(
        InferenceSettings(cache_dir=tmp_path, **settings),
        runtime=runtime,
        audio_separator=separator,
    )


async def _declared_only(app, path: str, length: int) -> tuple[int, dict[str, str]]:
    """Send headers that announce `length` bytes, and fail if the app asks for any of them."""
    sent: list[dict] = []

    async def receive():
        raise AssertionError("the body was read")

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"inference"), (b"content-length", str(length).encode())],
        "client": ("127.0.0.1", 1),
        "server": ("inference", 80),
    }
    await app(scope, receive, send)
    start = sent[0]
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/facts", "/audio/stems"])
async def test_a_declared_body_over_the_route_cap_is_refused_unread(tmp_path, path):
    app = _app(tmp_path, HeldSeparator())

    status, _ = await _declared_only(app, path, 1024 * 1024 * 1024)

    assert status == 413


@pytest.mark.asyncio
async def test_an_undeclared_body_is_cut_off_at_the_route_cap(tmp_path):
    separator = HeldSeparator()
    separator.release.set()
    app = _app(tmp_path, separator)

    async def endless():
        yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n\r\n'
        chunk = b"x" * (1024 * 1024)
        for _ in range(300):
            yield chunk

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inference") as client:
        response = await client.post(
            "/audio/stems",
            content=endless(),
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )

    assert response.status_code == 413
    assert separator.calls == 0


@pytest.mark.asyncio
async def test_a_second_separation_while_one_runs_is_told_to_retry(tmp_path):
    separator = HeldSeparator()
    app = _app(tmp_path, separator)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://inference") as client:
        first = asyncio.create_task(
            client.post("/audio/stems", files={"file": ("a.wav", b"audio")})
        )
        assert await asyncio.to_thread(separator.started.wait, 10)

        second = await client.post("/audio/stems", files={"file": ("b.wav", b"audio")})
        separator.release.set()
        finished = await first

    assert second.status_code == 429
    assert second.headers["Retry-After"]
    assert finished.status_code == 200
    assert separator.calls == 1


def test_a_picture_with_too_many_pixels_is_refused_by_name(tmp_path):
    buffer = BytesIO()
    # 60 MP in one bit a pixel: a few KB on the wire, far more once decoded.
    Image.new("1", (8000, 7500)).save(buffer, "PNG")
    image = base64.b64encode(buffer.getvalue()).decode()

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/facts", json={"image": image})

    assert response.status_code == 413
    assert "pixels" in response.json()["detail"]


def test_an_ordinary_picture_still_gets_its_facts(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (320, 240)).save(buffer, "JPEG")
    image = base64.b64encode(buffer.getvalue()).decode()

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/facts", json={"image": image})

    assert response.status_code == 200
    assert list(response.json()["producers"]) == [HEADS]
