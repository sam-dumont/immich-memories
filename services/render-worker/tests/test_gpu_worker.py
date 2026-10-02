"""One address retains the existing inference and authenticated render contracts."""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from immich_memories_render_worker.settings import WorkerSettings

from conftest import AUTH, WORKER_TOKEN, render_request_body, stub_artifact
from immich_memories_inference.gpu_phases import GpuPhases, PhaseBusy
from immich_memories_inference.gpu_worker import create_app
from immich_memories_inference.producers import Fact, ProducerFacts
from immich_memories_inference.runtime import ProducerRuntime
from immich_memories_inference.settings import InferenceSettings


class SyntheticProducer:
    """Model computation is replaced; the actual runtime and HTTP lifecycle remain."""

    name = "heads"
    encoder_key = "a" * 64
    versions = {"people": "public-v1"}

    def decide(self, image):
        return ProducerFacts("heads", self.encoder_key, (Fact("people", "public-v1", "yes", 0.75),))


class IdleRenderer:
    """Replace hardware probing, keeping both HTTP applications and lifespans real."""

    def health(self):
        return {"ready": True, "titles": "CUDA", "encoders": ["h264_nvenc"]}

    def render(self, request, directory, progress):
        raise AssertionError("this test submits no render")


def test_one_address_preserves_health_authentication_and_facts(tmp_path):
    runtime = ProducerRuntime({"heads": SyntheticProducer})
    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=runtime,
        renderer=IdleRenderer(),
    )

    with TestClient(app) as client:
        assert client.get("/ping").json() == "pong"
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/render/health").status_code == 401
        response = client.get("/render/health", headers=AUTH)
        assert response.json()["contract_version"] == 1
        assert response.json()["titles"] == "CUDA"
        facts = client.post("/facts", json={"image": "cGl4ZWxz"})
        assert facts.status_code == 200
        assert facts.json()["producers"]["heads"]["facts"][0]["label"] == "yes"
        assert runtime.loaded("heads") is not None

    assert runtime.loaded("heads") is None


async def test_same_phase_facts_wait_for_cleanup_then_both_enter_the_existing_queue(tmp_path):
    import asyncio

    import httpx

    from immich_memories_inference.caption_runtime import CaptionRuntime

    preparing = threading.Event()
    finish_cleanup = threading.Event()

    # WHY: replace external caption process cleanup, keeping phase admission,
    # both HTTP applications and the inference queue real.
    class BlockingCaptions(CaptionRuntime):
        armed = False
        cleanups = 0

        def stop(self):
            if self.armed:
                self.cleanups += 1
                preparing.set()
                assert finish_cleanup.wait(3)

    captions = BlockingCaptions()
    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SyntheticProducer}),
        renderer=IdleRenderer(),
        captions=captions,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client,
    ):
        captions.armed = True
        first = asyncio.create_task(client.post("/facts", json={"image": "cGl4ZWxz"}))
        second = None
        try:
            assert await asyncio.to_thread(preparing.wait, 2)
            second = asyncio.create_task(client.post("/facts", json={"image": "cGl4ZWxz"}))
            done, _pending = await asyncio.wait({second}, timeout=0.05)
            assert not done, "same-phase facts must wait for cleanup rather than fail admission"
        finally:
            finish_cleanup.set()
        assert (await first).status_code == 200
        assert second is not None and (await second).status_code == 200
        assert captions.cleanups == 1
        queue = (await client.get("/queue")).json()["producers"]["heads"]
        assert queue["completed"] == 2 and queue["rejected"] == 0
        captions.armed = False


async def test_same_phase_facts_retain_the_existing_queue_capacity(tmp_path):
    import asyncio

    import httpx

    deciding = threading.Event()
    finish = threading.Event()

    # WHY: replace native classifier execution with a bounded wait; HTTP
    # admission and the actual inference queue still enforce capacity.
    class SlowProducer(SyntheticProducer):
        def decide(self, image):
            deciding.set()
            assert finish.wait(3)
            return super().decide(image)

    app = create_app(
        InferenceSettings(cache_dir=tmp_path, request_threads=1, max_queued_requests=1),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SlowProducer}),
        renderer=IdleRenderer(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client,
    ):
        first = asyncio.create_task(client.post("/facts", json={"image": "cGl4ZWxz"}))
        second = None
        try:
            assert await asyncio.to_thread(deciding.wait, 2)
            second = asyncio.create_task(client.post("/facts", json={"image": "cGl4ZWxz"}))
            for _attempt in range(100):
                queue = (await client.get("/queue")).json()
                if queue["producers"]["heads"]["queued"] == 1:
                    break
                await asyncio.sleep(0.01)
            assert queue["capacity"] == 1 and queue["producers"]["heads"]["queued"] == 1
            body_reads = []

            async def overflow_body():
                body_reads.append(True)
                yield b'{"image": "cGl4ZWxz"}'

            overflow = await client.post(
                "/facts", content=overflow_body(), headers={"Content-Type": "application/json"}
            )
            assert body_reads == []
            assert overflow.status_code == 429
            assert overflow.headers["Retry-After"] == "1"
        finally:
            finish.set()
        assert (await first).status_code == 200
        assert second is not None and (await second).status_code == 200
        lane = (await client.get("/queue")).json()["producers"]["heads"]
        # Body admission rejects overflow before it can enter a producer lane.
        assert lane["completed"] == 2 and lane["rejected"] == 0
        assert lane["queued"] == lane["active"] == 0


def test_render_releases_models_then_refuses_model_work_until_it_finishes(tmp_path):
    started = threading.Event()
    release = threading.Event()
    runtime = ProducerRuntime({"heads": SyntheticProducer})

    class BlockingRenderer(IdleRenderer):
        def render(self, request, directory, progress):
            assert runtime.loaded("heads") is None
            started.set()
            assert release.wait(3)
            raise RuntimeError("synthetic rendering finished")

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=runtime,
        renderer=BlockingRenderer(),
    )
    image = {"image": "cGl4ZWxz"}
    with TestClient(app) as client:
        assert client.post("/facts", json=image).status_code == 200
        response = client.post(
            "/render/jobs",
            json=render_request_body(),
            headers=AUTH,
        )
        assert response.status_code == 202
        try:
            assert started.wait(2)
            assert client.post("/facts", json=image).status_code == 503
            assert client.get("/ping").status_code == 200
            assert client.get("/render/health", headers=AUTH).status_code == 200
        finally:
            release.set()


def test_render_waits_for_native_facts_before_unloading(tmp_path):
    deciding = threading.Event()
    finish_facts = threading.Event()
    rendering = threading.Event()

    class SlowProducer(SyntheticProducer):
        def decide(self, image):
            deciding.set()
            assert finish_facts.wait(3)
            return super().decide(image)

    runtime = ProducerRuntime({"heads": SlowProducer})

    class ObservingRenderer(IdleRenderer):
        def render(self, request, directory, progress):
            assert runtime.loaded("heads") is None
            rendering.set()
            raise RuntimeError("synthetic render finished")

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=runtime,
        renderer=ObservingRenderer(),
    )
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        facts = pool.submit(client.post, "/facts", json={"image": "cGl4ZWxz"})
        try:
            assert deciding.wait(2)
            response = client.post(
                "/render/jobs",
                json=render_request_body(),
                headers=AUTH,
            )
            assert response.status_code == 202
            assert not rendering.wait(0.05)
            assert runtime.loaded("heads") is not None
        finally:
            finish_facts.set()
        assert facts.result(timeout=2).status_code == 200
        assert rendering.wait(2)


async def test_render_wait_has_a_deadline_and_never_unloads_active_work():
    import asyncio

    released = []
    phases = GpuPhases(released.append, timeout=0.01)
    async with phases.models("facts"):

        def try_render():
            try:
                with phases.rendering():
                    raise AssertionError("active work was unloaded")
            except PhaseBusy:
                return "busy"

        assert await asyncio.to_thread(try_render) == "busy"
        assert released == ["facts"]
    with phases.rendering():
        assert released == ["facts", "render"]


async def test_a_failed_phase_cleanup_is_retried_before_admitting_work():
    attempts = []

    def release(phase):
        attempts.append(phase)
        if len(attempts) == 1:
            raise RuntimeError("cleanup failed")

    phases = GpuPhases(release)
    import pytest

    with pytest.raises(RuntimeError, match="cleanup failed"):
        async with phases.models("facts"):
            raise AssertionError("failed cleanup admitted native work")
    async with phases.models("facts"):
        assert attempts == ["facts", "facts"]


async def test_same_phase_cleanup_failure_never_admits_waiters_and_can_retry():
    import asyncio

    import pytest

    preparing = threading.Event()
    finish = threading.Event()
    attempts = []
    entered = []

    def release(phase):
        attempts.append(phase)
        if len(attempts) == 1:
            preparing.set()
            assert finish.wait(3)
            raise RuntimeError("synthetic cleanup failed")

    phases = GpuPhases(release)

    async def request():
        async with phases.models("facts"):
            entered.append("native work")

    first = asyncio.create_task(request())
    second = None
    try:
        assert await asyncio.to_thread(preparing.wait, 2)
        second = asyncio.create_task(request())
        await asyncio.sleep(0.01)
    finally:
        finish.set()
    with pytest.raises(RuntimeError, match="synthetic cleanup failed"):
        await first
    assert second is not None
    with pytest.raises(PhaseBusy, match="cleanup failed"):
        await second
    assert entered == []
    await request()
    assert attempts == ["facts", "facts"] and entered == ["native work"]


async def test_same_phase_preparation_deadline_keeps_cleanup_owned():
    import asyncio

    import pytest

    preparing = threading.Event()
    finish = threading.Event()
    released = []
    entered = []

    def release(phase):
        released.append(phase)
        preparing.set()
        assert finish.wait(3)

    phases = GpuPhases(release, timeout=0.01)

    async def request():
        async with phases.models("facts"):
            entered.append("facts")

    first = asyncio.create_task(request())
    try:
        assert await asyncio.to_thread(preparing.wait, 2)
        with pytest.raises(PhaseBusy, match="admission deadline"):
            await request()
        assert entered == [] and not first.done()

        def render():
            with phases.rendering():
                entered.append("render")

        with pytest.raises(PhaseBusy, match="render deadline"):
            await asyncio.to_thread(render)
        with pytest.raises(PhaseBusy, match="another phase"):
            async with phases.models("caption"):
                entered.append("caption")
        assert released == ["facts"] and entered == []
    finally:
        finish.set()
        await first
    assert entered == ["facts"]
    with phases.rendering():
        assert released == ["facts", "render"]


async def test_cancelling_a_same_phase_waiter_never_releases_the_preparing_owner():
    import asyncio

    import pytest

    preparing = threading.Event()
    finish = threading.Event()
    entered = []

    def release(phase):
        preparing.set()
        assert finish.wait(3)

    phases = GpuPhases(release, timeout=0.05)

    async def request(name):
        async with phases.models("facts"):
            entered.append(name)

    first = asyncio.create_task(request("owner"))
    second = None
    try:
        assert await asyncio.to_thread(preparing.wait, 2)
        second = asyncio.create_task(request("cancelled waiter"))
        await asyncio.sleep(0.01)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert entered == []

        def render():
            with phases.rendering():
                entered.append("render")

        with pytest.raises(PhaseBusy, match="render deadline"):
            await asyncio.to_thread(render)
        assert not first.done()
    finally:
        finish.set()
        await first
    assert entered == ["owner"]
    with phases.rendering():
        pass


async def test_repeated_client_cancellation_keeps_native_work_reserved(tmp_path):
    import asyncio

    import httpx
    import pytest

    deciding = threading.Event()
    finish = threading.Event()

    class SlowProducer(SyntheticProducer):
        def decide(self, image):
            deciding.set()
            assert finish.wait(3)
            return super().decide(image)

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SlowProducer}),
        renderer=IdleRenderer(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as client,
    ):
        facts = asyncio.create_task(client.post("/facts", json={"image": "cGl4ZWxz"}))
        caption = None
        try:
            assert await asyncio.to_thread(deciding.wait, 2)
            facts.cancel()
            await asyncio.sleep(0.01)
            facts.cancel()
            caption = asyncio.create_task(client.get("/v1/models"))
            done, _pending = await asyncio.wait({caption}, timeout=0.2)
            assert caption in done, (
                "phase cleanup blocked on cancelled but still-running native work"
            )
            assert caption.result().status_code == 503
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await facts
            if caption is not None:
                await caption


def test_caption_stream_drops_render_credentials_and_stops_before_render(tmp_path):
    import socket
    import sys
    from pathlib import Path

    from immich_memories_inference.caption_runtime import CaptionRuntime

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    captions = CaptionRuntime(
        port=port,
        command=[
            sys.executable,
            str(Path(__file__).parent / "fixtures/caption_runtime.py"),
            str(port),
        ],
        startup_timeout=2,
    )
    started = threading.Event()

    class ObservingRenderer(IdleRenderer):
        def render(self, request, directory, progress):
            assert not captions.running
            started.set()
            raise RuntimeError("synthetic render finished")

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SyntheticProducer}),
        renderer=ObservingRenderer(),
        captions=captions,
    )
    with TestClient(app) as client:
        assert not captions.running
        response = client.post(
            "/v1/chat/completions",
            json={"stream": True},
            headers=AUTH,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "caption" in response.text and "data: [DONE]" in response.text
        assert captions.running
        response = client.post(
            "/render/jobs",
            json=render_request_body(),
            headers=AUTH,
        )
        assert response.status_code == 202
        assert started.wait(2)
        assert client.get("/v1/models").json()["data"][0]["id"] == "synthetic-captioner"
        assert (
            client.get("/v1/models", params={"compressed": "1"}).json()["data"][0]["id"]
            == "synthetic-captioner"
        )
        assert captions.running
    assert not captions.running


def test_prefixed_render_job_returns_the_validated_film_once(tmp_path):
    import time

    class TinyRenderer(IdleRenderer):
        def render(self, request, directory, progress):
            return stub_artifact(directory)

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SyntheticProducer}),
        renderer=TinyRenderer(),
    )
    with TestClient(app, headers=AUTH) as client:
        submission = client.post("/render/jobs", json=render_request_body())
        assert submission.status_code == 202
        job_id = submission.json()["job_id"]
        for _attempt in range(200):
            result = client.get(f"/render/jobs/{job_id}").json()
            if result["state"] in {"ready", "failed"}:
                break
            time.sleep(0.01)
        assert result["state"] == "ready", result
        assert result["probe"]["decoded_frames"] == 30
        film = client.get(f"/render/jobs/{job_id}/output")
        assert film.status_code == 200 and len(film.content) > 100
        assert film.headers["repr-digest"].startswith("sha-256=")
        assert client.get(f"/render/jobs/{job_id}/output").status_code == 410


def test_combined_worker_keeps_the_demucs_http_contract(tmp_path):
    from io import BytesIO
    from zipfile import ZipFile

    from immich_memories.audio.music_generator_models import MusicStems

    class Separator:
        async def separate_stems(self, source, folder, progress_callback=None):
            paths = {}
            for name in ("drums", "bass", "other", "vocals"):
                paths[name] = folder / f"{name}.wav"
                paths[name].write_bytes(source.read_bytes())
            return MusicStems(**paths)

    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SyntheticProducer}),
        renderer=IdleRenderer(),
        audio_separator=Separator(),
    )
    with TestClient(app) as client:
        response = client.post("/audio/stems", files={"file": ("track.wav", b"synthetic music")})
        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {"drums.wav", "bass.wav", "other.wav", "vocals.wav"}
            assert archive.read("vocals.wav") == b"synthetic music"
    assert not list(tmp_path.glob("demucs-*"))


def test_caption_start_failure_is_safe_and_other_phases_keep_working(tmp_path):
    from immich_memories_inference.caption_runtime import CaptionRuntime

    captions = CaptionRuntime(command=[str(tmp_path / "private-runtime-that-does-not-exist")])
    app = create_app(
        InferenceSettings(cache_dir=tmp_path),
        WorkerSettings(token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=tmp_path),
        runtime=ProducerRuntime({"heads": SyntheticProducer}),
        renderer=IdleRenderer(),
        captions=captions,
    )
    with TestClient(app) as client:
        response = client.get("/v1/models")
        assert response.status_code == 503
        assert "private-runtime" not in response.text
        assert not captions.running
        assert client.post("/facts", json={"image": "cGl4ZWxz"}).status_code == 200


def test_caption_readiness_deadline_kills_and_reaps_unresponsive_process(tmp_path):
    import os
    import sys

    import pytest

    from immich_memories_inference.caption_runtime import CaptionRuntime, CaptionUnavailable

    pid_file = tmp_path / "pid"
    program = (
        "import os, pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    captions = CaptionRuntime(
        command=[sys.executable, "-c", program], startup_timeout=0.5, stop_timeout=0.05
    )
    with pytest.raises(CaptionUnavailable):
        captions.start()
    assert not captions.running
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
