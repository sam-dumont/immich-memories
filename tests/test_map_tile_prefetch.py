"""A map card fetches the tiles of its coming frames while the current frame renders.

A local tile server answers every request after a fixed delay, so the tests see what a
render worker on a real network sees. Nothing here reaches a real tile host.
"""

from __future__ import annotations

import hashlib
import io
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from PIL import Image, ImageDraw

from immich_memories.titles import map_animation

_LATENCY = 0.03
_ENCODE = 0.002
_AHEAD = map_animation._LOOKAHEAD_VIEWS


class _SlowTileServer:
    """Serves one tile after ``latency`` seconds and counts the requests per path."""

    def __init__(self, latency: float, fail_first: int = 0, failure: int = 503) -> None:
        image = Image.new("RGB", (256, 256), (40, 80, 120))
        ImageDraw.Draw(image).rectangle((0, 0, 127, 127), fill=(180, 40, 90))
        encoded = io.BytesIO()
        image.save(encoded, "JPEG")
        body = encoded.getvalue()
        self.requests: dict[str, int] = {}
        self.ahead_seen: list[int] = []
        lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with lock:
                    server.requests[self.path] = server.requests.get(self.path, 0) + 1
                    attempt = server.requests[self.path]
                    server.ahead_seen.append(len(map_animation.tile_cache.ahead))
                time.sleep(latency)
                if attempt <= fail_first:
                    self.send_response(failure)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self._http.server_port}/{{z}}/{{y}}/{{x}}"

    def __enter__(self) -> _SlowTileServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._http.shutdown()
        self._http.server_close()
        self._thread.join()


class _TimedEncoder:
    """Stands in for FFmpeg and its stderr reader: hashes each frame and notes the tile cache."""

    returncode = 0
    stderr = None
    frames: list[str] = []
    ahead_seen: list[int] = []
    # Per frame written: the tiles it drew, and every tile stored or asked for by then.
    drawn: list[frozenset[str]] = []
    requested: list[frozenset[str]] = []
    unreachable: list[bool] = []

    def __init__(self, *_args, **_kwargs):
        self.stdin = self

    def write(self, data):
        type(self).frames.append(hashlib.sha256(data).hexdigest())
        cache = map_animation.tile_cache
        type(self).ahead_seen.append(len(cache.ahead))
        type(self).drawn.append(cache.in_view)
        type(self).unreachable.append(cache.unreachable)
        # dict.copy and set.copy are single steps, safe against the fetching threads.
        type(self).requested.append(frozenset(cache.content.copy()) | cache.ahead.copy())
        time.sleep(_ENCODE)
        return len(data)

    def close(self):
        pass

    def wait(self):
        return 0

    def start(self):
        return self

    def stop(self):
        return ""


@pytest.fixture
def card(monkeypatch, tmp_path):
    # WHY: the FFmpeg encode is replaced by a fixed per-frame cost; its frames are hashed.
    monkeypatch.setattr(map_animation.subprocess, "Popen", _TimedEncoder)
    # WHY: the stderr reader thread needs a real encoder pipe.
    monkeypatch.setattr(map_animation, "StderrDrain", _TimedEncoder)
    map_animation.tile_cache.clear()

    def render(server: _SlowTileServer, lookahead: int) -> list[str]:
        # WHY: point the card at the local slow tile server instead of the satellite host.
        monkeypatch.setattr(map_animation, "_SAT_URL", server.url)
        monkeypatch.setattr(map_animation, "_LOOKAHEAD_VIEWS", lookahead)
        _TimedEncoder.frames = []
        _TimedEncoder.ahead_seen = []
        _TimedEncoder.drawn = []
        _TimedEncoder.requested = []
        _TimedEncoder.unreachable = []
        map_animation.tile_cache.clear()
        map_animation.create_map_move_video(
            (10.0, 20.0), (10.9, 21.3), "", tmp_path / "card.mp4", 4.0, 320, 180, 15
        )
        return _TimedEncoder.frames

    yield render
    map_animation.tile_cache.clear()


def _frames_that_waited_on_unrequested_tiles() -> list[int]:
    """Frames whose tiles were not all stored or asked for when the frame before was done.

    Frame N renders right after frame N-1 is written, so a tile missing from that
    snapshot is one frame N had to start fetching itself, and wait for.
    """
    drawn, requested = _TimedEncoder.drawn, _TimedEncoder.requested
    return [n for n in range(1, len(drawn)) if not drawn[n] <= requested[n - 1]]


def test_after_the_first_view_no_frame_waits_on_a_tile_nobody_asked_for(
    card, tmp_path, monkeypatch
):
    from immich_memories.processing import memory_budget

    # WHY: a real cgroup file fixture fixes the tile cache's budget on every runner.
    (tmp_path / "memory.max").write_text(str(4 * 2**30))
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    with _SlowTileServer(_LATENCY) as server:
        frame_by_frame = card(server, lookahead=0)
        waited_frame_by_frame = _frames_that_waited_on_unrequested_tiles()
    with _SlowTileServer(_LATENCY) as server:
        frames = card(server, lookahead=_AHEAD)
        waited_ahead = _frames_that_waited_on_unrequested_tiles()

    assert frames == frame_by_frame
    assert sum(server.requests.values()) >= 40
    # Frame by frame, the camera keeps reaching tiles that no one has asked for yet.
    assert len(waited_frame_by_frame) >= 5
    # Fetching ahead, every frame's tiles were on their way before it started.
    assert waited_ahead == []


def test_no_tile_is_fetched_twice_in_a_card(card):
    with _SlowTileServer(_LATENCY) as server:
        card(server, lookahead=_AHEAD)

    assert server.requests and set(server.requests.values()) == {1}


def test_fetching_ahead_keeps_the_three_attempts_and_never_doubles_them(card):
    with _SlowTileServer(0.005, fail_first=2) as server:
        frames = card(server, lookahead=_AHEAD)

    assert frames
    assert server.requests and set(server.requests.values()) == {3}


def test_tiles_fetched_ahead_stay_inside_the_tile_cache_budget(card, tmp_path, monkeypatch):
    from immich_memories.processing import memory_budget

    # WHY: a real cgroup file fixture leaves the tile cache room for six decoded tiles.
    (tmp_path / "memory.max").write_text(str(6 * 256 * 256 * 4 * 32))
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    with _SlowTileServer(0) as server:
        expected = card(server, lookahead=0)
    with _SlowTileServer(_LATENCY) as server:
        frames = card(server, lookahead=_AHEAD)

    assert map_animation.tile_cache.limit == 6 * 256 * 256 * 4
    assert frames == expected
    seen = server.ahead_seen + _TimedEncoder.ahead_seen
    assert max(seen) <= 6
    assert max(seen) > 0
    assert set(server.requests.values()) == {1}


def test_a_card_that_ends_leaves_no_fetch_running(card):
    with _SlowTileServer(_LATENCY) as server:
        card(server, lookahead=_AHEAD)
        requested = dict(server.requests)
        time.sleep(4 * _LATENCY)

    assert server.requests == requested
    assert not map_animation.tile_cache.ahead
    assert {urlparse(url).path for url in map_animation.tile_cache.content} <= set(requested)


_FOREVER = 10**9


@pytest.mark.parametrize("failure", [403, 404])
def test_a_card_stops_asking_a_tile_host_that_refuses(card, failure):
    with _SlowTileServer(0, fail_first=_FOREVER, failure=failure) as server:
        frames = card(server, lookahead=_AHEAD)

    # The card still renders every frame, on the grey fallback, after a handful of asks.
    assert len(frames) == 60
    assert all(_TimedEncoder.unreachable[1:])
    assert 0 < sum(server.requests.values()) <= 8
    assert set(server.requests.values()) == {1}


def test_a_card_gives_up_on_a_tile_host_that_keeps_failing(card):
    with _SlowTileServer(0, fail_first=_FOREVER) as server:
        frames = card(server, lookahead=_AHEAD)

    # Three attempts for the tiles the first frame asked for, then nothing more.
    assert len(frames) == 60
    assert set(server.requests.values()) <= {1, 2, 3}
    assert sum(server.requests.values()) <= 3 * 24


def test_a_card_stops_asking_a_tile_host_that_refuses_the_connection(card, monkeypatch):
    import socket

    from immich_memories.titles.map_tiles import _tile_client

    with socket.create_server(("127.0.0.1", 0)) as closed:
        port = closed.getsockname()[1]
    attempts = []
    get = _tile_client.get

    def counted(url, **kwargs):
        attempts.append(url)
        return get(url, **kwargs)

    # WHY: a refused connection never reaches a server, so the client side counts the tries.
    monkeypatch.setattr(_tile_client, "get", counted)
    server = _SlowTileServer(0)
    server.url = f"http://127.0.0.1:{port}/{{z}}/{{y}}/{{x}}"
    frames = card(server, lookahead=_AHEAD)

    assert len(frames) == 60
    assert 0 < len(attempts) <= 8


def test_a_tile_that_fails_once_is_fetched_again_and_the_card_keeps_its_map(card, monkeypatch):
    import httpx

    from immich_memories.titles.map_tiles import _tile_client

    with _SlowTileServer(0) as server:
        expected = card(server, lookahead=_AHEAD)
        failed: list[str] = []
        get = _tile_client.get

        def blip(url, **kwargs):
            if not failed:
                failed.append(url)
                raise httpx.ReadError("connection reset by peer")
            return get(url, **kwargs)

        # WHY: a reset on one request is a client-side error; the tile server cannot send one.
        monkeypatch.setattr(_tile_client, "get", blip)
        frames = card(server, lookahead=_AHEAD)

    assert failed
    assert not any(_TimedEncoder.unreachable)
    assert frames == expected
