"""A busy inference worker is waited for, not recorded as a failed picture (#2781)."""

import http.server
import io
import json
import threading

import pytest
from PIL import Image

from immich_memories.analysis.captions import requests as captions
from immich_memories.analysis.captions import worker_wait
from immich_memories.analysis.captions.contract import API_MODEL
from immich_memories.operations.cancellation import check_cancelled
from tests.annotation_rows import annotation_store, count_rows

BUSY = b'{"detail": "GPU is busy with another phase"}'
ANSWER = json.dumps(
    {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"description": "A dog.", "setting": "a park"})},
            }
        ],
        "usage": {"completion_tokens": 5, "prompt_tokens": 50},
    }
).encode()
INVENTORY = json.dumps({"data": [{"id": API_MODEL, "owned_by": "test"}]}).encode()


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (100, 80), (110, 70, 30)).save(out, "JPEG")
    return out.getvalue()


class _Worker:
    """A fake inference worker: answers `busy_answers` busy replies, then 200 for good."""

    def __init__(self, busy_answers: int | None, *, status=503, retry_after=None, reset=False):
        self.requests = 0
        self.busy_left = busy_answers
        worker = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _reply(self, status_code: int, body: bytes, extra=None) -> None:
                self.send_response(status_code)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _serve(self, ok: bytes) -> None:
                if self.command == "POST":
                    self.rfile.read(int(self.headers.get("Content-Length", 0)))
                worker.requests += 1
                if worker.busy_left is None or worker.busy_left > 0:
                    if worker.busy_left is not None:
                        worker.busy_left -= 1
                    if reset:
                        self.connection.close()
                        return
                    extra = {"Retry-After": str(retry_after)} if retry_after is not None else None
                    self._reply(status, BUSY, extra)
                    return
                self._reply(200, ok)

            def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
                self._serve(INVENTORY)

            def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's name
                self._serve(ANSWER)

            def log_message(self, *args: object) -> None:
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def clock(monkeypatch):
    """Virtual time: sleeping advances the clock, so a 25 minute wait costs nothing."""
    state = {"now": 0.0, "sleeps": []}

    def sleep(seconds: float) -> None:
        state["sleeps"].append(seconds)
        state["now"] += seconds

    # WHY: the wall clock; the bound is minutes long and a test must not spend them.
    monkeypatch.setattr(worker_wait, "_sleep", sleep)
    monkeypatch.setattr(worker_wait, "_clock", lambda: state["now"])
    return state


@pytest.fixture
def worker(request):
    made = []

    def make(*args, **kwargs):
        made.append(_Worker(*args, **kwargs))
        return made[-1]

    yield make
    for each in made:
        each.close()


def _ask(url: str) -> captions.CallOutcome:
    return captions._ask_one(url, _jpeg(), timeout=5, api_key="")


def test_a_worker_busy_for_a_while_then_free_answers_the_picture(worker, clock):
    busy = worker(4)
    outcome = _ask(busy.base_url)
    assert outcome.error is None
    assert outcome.envelope is not None
    assert busy.requests == 5
    assert clock["now"] > 0


def test_the_workers_retry_after_is_honoured(worker, clock):
    busy = worker(2, retry_after=7)
    assert _ask(busy.base_url).error is None
    assert clock["sleeps"] == [7.0, 7.0]


def test_a_reset_connection_is_waited_out_like_a_busy_answer(worker, clock):
    flaky = worker(2, reset=True)
    assert _ask(flaky.base_url).error is None
    assert flaky.requests == 3


def test_too_many_requests_is_waited_out(worker, clock):
    limited = worker(1, status=429)
    assert _ask(limited.base_url).error is None


def test_a_real_per_picture_error_is_not_retried(worker, clock):
    broken = worker(None, status=422)
    outcome = _ask(broken.base_url)
    assert outcome.error == "http_422"
    assert broken.requests == 1
    assert clock["now"] == 0


def test_the_provider_check_waits_for_a_busy_worker_too(worker, clock):
    busy = worker(3)
    inventory = captions._model_inventory(busy.base_url, timeout=5, api_key="")
    assert [row["id"] for row in inventory] == [API_MODEL]


def test_a_worker_that_stays_busy_past_the_bound_fails_the_run_once_saying_so(worker, clock):
    stuck = worker(None)
    with pytest.raises(captions.CaptionServerBusy, match="stayed busy"):
        _ask(stuck.base_url)
    assert clock["now"] <= worker_wait.WORKER_MAX_WAIT_SECONDS
    assert clock["now"] >= worker_wait.WORKER_MAX_WAIT_SECONDS - worker_wait.MAX_DELAY_SECONDS


def test_preparation_survives_a_busy_spell_and_banks_every_picture(worker, clock):
    busy = worker(6)
    store = annotation_store()
    failures = captions.prepare_captions(
        store=store,
        asset_ids=("a", "b"),
        preview_for=lambda _: _jpeg(),
        base_url=busy.base_url,
        timeout=5,
        concurrency=2,
        check_cancelled=check_cancelled,
        progress=lambda *_: None,
    )
    assert failures == {}
    assert count_rows(store, "descriptions") == 2


def test_preparation_stops_once_when_the_worker_never_frees_up(worker, clock):
    stuck = worker(None)
    with pytest.raises(captions.CaptionServerBusy, match="stayed busy"):
        captions.prepare_captions(
            store=annotation_store(),
            asset_ids=("a", "b", "c", "d"),
            preview_for=lambda _: _jpeg(),
            base_url=stuck.base_url,
            timeout=5,
            concurrency=2,
            check_cancelled=check_cancelled,
            progress=lambda *_: None,
        )
