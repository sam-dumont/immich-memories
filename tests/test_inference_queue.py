"""Busy model requests wait visibly without occupying all inference workers."""

import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from immich_memories_inference.app import create_app
from immich_memories_inference.runtime import ProducerRuntime
from immich_memories_inference.settings import InferenceSettings
from tests.test_inference_service import CountingProducer, photograph


def test_busy_model_reports_waiting_work_while_another_model_can_finish():
    entered, release = threading.Event(), threading.Event()

    class HeldProducer(CountingProducer):
        # WHY: the native model boundary is held until the public queue is observed.
        def decide(self, image):
            entered.set()
            assert release.wait(5)
            return super().decide(image)

    runtime = ProducerRuntime(
        {"heads": lambda: HeldProducer([]), "other": lambda: CountingProducer([])}
    )
    image = base64.b64encode(photograph()).decode()
    with TestClient(create_app(InferenceSettings(request_threads=2), runtime=runtime)) as client:
        with ThreadPoolExecutor(max_workers=2) as callers:
            first = callers.submit(
                client.post, "/facts", json={"image": image, "producers": ["heads"]}
            )
            try:
                assert entered.wait(2)
                second = callers.submit(
                    client.post, "/facts", json={"image": image, "producers": ["heads"]}
                )
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    response = client.get("/queue")
                    assert response.status_code == 200
                    state = response.json()["producers"]["heads"]
                    if state["queued"] == 1:
                        break
                    time.sleep(0.01)
                assert state["active"] == 1 and state["queued"] == 1
                assert state["oldest_wait_seconds"] >= 0
                # Both executor workers used to be occupied by the held model.
                answer = client.post("/facts", json={"image": image, "producers": ["other"]})
                assert answer.status_code == 200
            finally:
                release.set()
            assert first.result().status_code == second.result().status_code == 200
        state = client.get("/queue").json()["producers"]["heads"]
        assert (state["active"], state["queued"], state["completed"]) == (0, 0, 2)
        assert state["mean_wait_seconds"] > 0
        assert state["mean_run_seconds"] > 0


def test_full_queue_returns_retry_after_and_recovers_after_work_finishes():
    entered, release = threading.Event(), threading.Event()

    class HeldProducer(CountingProducer):
        # WHY: holding the model makes queue admission deterministic through HTTP.
        def decide(self, image):
            entered.set()
            assert release.wait(5)
            return super().decide(image)

    runtime = ProducerRuntime({"heads": lambda: HeldProducer([])})
    app = create_app(InferenceSettings(max_queued_requests=1), runtime=runtime)
    payload = {"image": base64.b64encode(photograph()).decode()}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(client.post, "/facts", json=payload)
        try:
            assert entered.wait(2)
            second = callers.submit(client.post, "/facts", json=payload)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = client.get("/queue").json()
                if state["producers"]["heads"]["queued"] == 1:
                    break
                time.sleep(0.01)
            refused = client.post("/facts", json=payload)
            assert refused.status_code == 429
            assert int(refused.headers["Retry-After"]) > 0
            state = client.get("/queue").json()
            assert state["capacity"] == 1
            assert state["producers"]["heads"]["rejected"] == 1
        finally:
            release.set()
        assert first.result().status_code == second.result().status_code == 200
        assert client.post("/facts", json=payload).status_code == 200


async def test_cancellation_removes_waiters_but_keeps_running_native_work_reserved():
    import asyncio

    import pytest

    from immich_memories_inference.queue import InferenceQueue

    entered, release = threading.Event(), threading.Event()

    def native_work():
        # WHY: a native inference call cannot be stopped by cancelling its HTTP waiter.
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as workers:
        queue = InferenceQueue(("heads",), workers, 1, 1)
        active = asyncio.create_task(queue.run("heads", native_work))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            waiting = asyncio.create_task(queue.run("heads", lambda: None))
            await asyncio.sleep(0)
            assert queue.snapshot()["producers"]["heads"]["queued"] == 1
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            active.cancel()
            await asyncio.sleep(0)
            state = queue.snapshot()["producers"]["heads"]
            assert (state["active"], state["queued"]) == (1, 0)
            assert not active.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await active
        state = queue.snapshot()["producers"]["heads"]
        assert (state["active"], state["queued"], state["cancelled"]) == (0, 0, 2)
        assert await queue.run("heads", lambda: "recovered") == "recovered"


def test_bad_image_is_counted_without_poisoning_the_queue():
    class RefusingProducer(CountingProducer):
        # WHY: the model's image decode error crosses the public HTTP failure boundary.
        def decide(self, image):
            raise ValueError("unreadable image")

    runtime = ProducerRuntime({"heads": lambda: RefusingProducer([])})
    with TestClient(create_app(runtime=runtime)) as client:
        payload = {"image": base64.b64encode(b"bad image").decode()}
        assert client.post("/facts", json=payload).status_code == 400
        state = client.get("/queue").json()["producers"]["heads"]
        assert (state["active"], state["queued"], state["failed"]) == (0, 0, 1)
