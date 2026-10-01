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
def tile_server(monkeypatch):
    image = Image.new("RGB", (256, 256), (40, 80, 120))
    ImageDraw.Draw(image).rectangle((0, 0, 127, 127), fill=(180, 40, 90))
    encoded = io.BytesIO()
    image.save(encoded, "PNG")
    body = encoded.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
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
    map_animation._tile_cache.clear()
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        map_animation._tile_cache.clear()


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
    renderer = map_animation._CachedStaticMap(320, 180, url_template=tile_server)
    renderer.add_marker(CircleMarker((2.35, 48.86), "red", 12))

    frame = renderer.render(zoom=12, center=[2.35, 48.86])

    assert frame.getpixel((160, 90)) == (255, 0, 0)
