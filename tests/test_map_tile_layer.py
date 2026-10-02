"""Satellite frames do not need StaticMap's supersampled feature surface."""

import io
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image, ImageDraw
from staticmap import CircleMarker, StaticMap

from immich_memories.titles import map_animation


@pytest.fixture
def tile_requests():
    return {}


@pytest.fixture
def tile_server(monkeypatch, request, tile_requests):
    image = Image.new("RGB", (256, 256), (40, 80, 120))
    ImageDraw.Draw(image).rectangle((0, 0, 127, 127), fill=(180, 40, 90))
    encoded = io.BytesIO()
    tile_format = getattr(request, "param", "PNG")
    if tile_format == "transparent":
        image = image.convert("RGBA")
        image.putalpha(128)
    image.save(encoded, "JPEG" if tile_format == "JPEG" else "PNG")
    body = encoded.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            tile_requests[self.path] = tile_requests.get(self.path, 0) + 1
            if tile_format == "offline" or (
                tile_format == "retry" and tile_requests[self.path] < 3
            ):
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/{{z}}/{{y}}/{{x}}"
    # WHY: use real HTTP and image decoding against a local deterministic tile server.
    monkeypatch.setattr(map_animation, "_SAT_URL", url)
    map_animation.tile_cache.clear()
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        map_animation.tile_cache.clear()


def test_satellite_render_allocates_no_unused_feature_surface(tile_server, monkeypatch):
    allocations = []
    original = Image.new

    def allocate(mode, size, *args, **kwargs):
        if mode == "RGBA":
            allocations.append(size)
        return original(mode, size, *args, **kwargs)

    # WHY: count real allocations; identical pixels cannot reveal this wasted surface.
    monkeypatch.setattr(Image, "new", allocate)
    frame = map_animation._render_satellite(48.86, 2.35, 12.5, 320, 180)

    assert frame.size == (320, 180)
    assert len(frame.getcolors(320 * 180)) > 1
    assert allocations == []


@pytest.mark.parametrize(
    "lat,lon,zoom,width,height",
    [
        (48.86, 2.35, 12.0, 320, 180),
        (48.86, 2.35, 12.01, 320, 180),
        (48.86, 2.35, 12.99, 320, 180),
        (48.86, 2.35, 12.5, 180, 320),
        (0.0, 179.99, 3.1, 320, 180),
        (80.0, -179.99, 7.3, 320, 180),
    ],
)
def test_map_pixels_match_the_previous_feature_path(tile_server, lat, lon, zoom, width, height):
    level = math.ceil(zoom)
    scale = 2 ** (level - zoom)
    old = StaticMap(math.ceil(width * scale), math.ceil(height * scale), url_template=tile_server)
    old.add_marker(CircleMarker((lon, lat), "#00000000", 1))
    expected = old.render(zoom=level, center=[lon, lat])
    expected = expected.resize((width, height), Image.Resampling.LANCZOS)

    actual = map_animation._render_satellite(lat, lon, zoom, width, height)

    assert actual.mode == expected.mode == "RGB"
    assert actual.tobytes() == expected.tobytes()


def test_real_features_are_still_drawn_when_requested(tile_server):
    renderer = map_animation.CachedStaticMap(320, 180, url_template=tile_server)
    renderer.add_marker(CircleMarker((2.35, 48.86), "red", 12))

    frame = renderer.render(zoom=12, center=[2.35, 48.86])

    assert frame.getpixel((160, 90)) == (255, 0, 0)


def test_warm_satellite_frame_reuses_decoded_tiles(tile_server, monkeypatch):
    decodes = []
    original = Image.open

    def decode(*args, **kwargs):
        decodes.append(1)
        return original(*args, **kwargs)

    # WHY: count real image decodes; pixel comparisons cannot detect repeated work.
    monkeypatch.setattr(Image, "open", decode)
    first = map_animation._render_satellite(48.86, 2.35, 12.5, 320, 180)
    assert decodes
    decodes.clear()

    second = map_animation._render_satellite(48.86, 2.35, 12.5, 320, 180)

    assert first.tobytes() == second.tobytes()
    assert decodes == []


@pytest.mark.parametrize("tile_server", ["JPEG", "transparent"], indirect=True)
def test_cached_jpeg_and_alpha_tiles_match_upstream_pixels(tile_server):
    expected = StaticMap(320, 180, url_template=tile_server).render(zoom=12, center=[2.35, 48.86])
    for _ in range(2):
        actual = map_animation._render_satellite(48.86, 2.35, 12.0, 320, 180)
        assert actual.tobytes() == expected.tobytes()


def test_decoded_cache_evicts_pixels_without_invalidating_borrowed_frames(tmp_path, monkeypatch):
    from immich_memories.processing import memory_budget
    from immich_memories.titles.map_tiles import TileCache

    # WHY: a real cgroup file fixture makes the cache's memory budget one RGBA tile.
    (tmp_path / "memory.max").write_text(str(256 * 256 * 4 * 32))
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    cache = TileCache()
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (10, 20, 30)).save(buffer, "PNG")
    content = buffer.getvalue()
    first = cache.decode("first", content)
    assert cache.decode("first", content) is first
    second = cache.decode("second", content)
    assert cache.decode("second", content) is second
    assert cache.decode("first", content) is not first
    assert first.getpixel((0, 0)) == (10, 20, 30, 255)
    cache.clear()
    assert cache.decode("second", content) is not second


@pytest.mark.parametrize("tile_server", ["retry"], indirect=True)
def test_cold_tiles_keep_three_attempts_then_reuse_the_download(tile_server, tile_requests):
    from immich_memories.titles.map_tiles import CachedStaticMap

    renderer = CachedStaticMap(320, 180, url_template=tile_server)
    first = renderer.render(zoom=12, center=[2.35, 48.86])
    second = renderer.render(zoom=12, center=[2.35, 48.86])

    assert first.tobytes() == second.tobytes()
    assert len(first.getcolors(320 * 180)) > 1
    assert tile_requests and set(tile_requests.values()) == {3}


@pytest.mark.parametrize("tile_server", ["offline"], indirect=True)
def test_permanent_tile_failure_stops_after_three_attempts_without_urls(tile_server, tile_requests):
    from immich_memories.titles.map_tiles import CachedStaticMap

    renderer = CachedStaticMap(320, 180, url_template=tile_server)
    with pytest.raises(RuntimeError, match=r"^could not download \d+ tiles$"):
        renderer.render(zoom=12, center=[2.35, 48.86])
    assert tile_requests and set(tile_requests.values()) == {3}


def test_frame_uses_resident_tiles_before_eviction(tile_server, tmp_path, monkeypatch):
    from immich_memories.processing import memory_budget

    # WHY: the cgroup fixture leaves room for half of this view's six tiles.
    (tmp_path / "memory.max").write_text(str(3 * 256 * 256 * 4 * 32))
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    map_animation.tile_cache.clear()
    decodes = []
    original = Image.open

    def decode(*args, **kwargs):
        decodes.append(1)
        return original(*args, **kwargs)

    # WHY: observe real decode work under eviction, while keeping actual pixels and HTTP.
    monkeypatch.setattr(Image, "open", decode)
    first = map_animation._render_satellite(48.86, 2.35, 12.5, 320, 180)
    assert len(decodes) == 6
    decodes.clear()
    second = map_animation._render_satellite(48.86, 2.35, 12.5, 320, 180)

    assert second.tobytes() == first.tobytes()
    assert len(decodes) == 3


@pytest.mark.parametrize("failed", [False, True])
def test_card_releases_decoded_pixels_even_when_encoding_fails(
    tile_server, tmp_path, monkeypatch, failed
):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buffer, "PNG")
    content = buffer.getvalue()
    borrowed = []

    def encode(*_args):
        map_animation.tile_cache.content["tile"] = content
        borrowed.append(map_animation.tile_cache.decode("tile", content))
        if failed:
            raise RuntimeError("encoder failed")
        return 1

    # WHY: replace the FFmpeg write boundary; this test covers card-owned cache lifetime.
    monkeypatch.setattr(map_animation, "_pipe_frames", encode)
    kwargs = {"width": 320, "height": 180, "fps": 30}
    if failed:
        with pytest.raises(RuntimeError, match="encoder failed"):
            map_animation.create_map_move_video(
                (0, 0), (1, 1), "", tmp_path / "card.mp4", 1, **kwargs
            )
    else:
        map_animation.create_map_move_video((0, 0), (1, 1), "", tmp_path / "card.mp4", 1, **kwargs)
    assert len(map_animation.tile_cache) == 0
    assert map_animation.tile_cache.decode("tile", content) is not borrowed[0]
