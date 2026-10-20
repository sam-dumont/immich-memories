"""Satellite tiles: retain downloads and a bounded working set of decoded pixels."""

from __future__ import annotations

import io
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor

import httpx
from PIL import Image
from staticmap import StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

from immich_memories.processing.memory_budget import memory_budget

_OPAQUE_MODES = frozenset({"RGB", "L", "CMYK", "YCbCr"})
# StaticMap's request policy, kept for every fetch: four at a time, three attempts each.
_FETCH_THREADS = 4
_FETCH_ATTEMPTS = 3
# A decoded RGBA tile: what a tile fetched ahead may cost once it is drawn.
_TILE_PIXEL_BYTES = 256 * 256 * 4

TileResponse = tuple[int | None, bytes | None]

# One client for every tile request: staticmap's own `requests.get` opened a new
# connection (and TLS handshake) per tile, which left a moving card waiting on the
# network at about 7 fps. A frame's fetches and the look-ahead each run four at a time.
_tile_client = httpx.Client(
    follow_redirects=True,
    limits=httpx.Limits(
        max_connections=2 * _FETCH_THREADS, max_keepalive_connections=2 * _FETCH_THREADS
    ),
)


def _download(url: str, timeout: float | None, headers: dict[str, str]) -> TileResponse:
    response = _tile_client.get(url, timeout=timeout, headers=headers)
    return response.status_code, response.content


class TileCache:
    def __init__(self):
        self.content: dict[str, bytes] = {}
        self.images: OrderedDict[str, Image.Image] = OrderedDict()
        # The tiles of the last frame drawn: where a card lands, the next one takes off.
        self.in_view: frozenset[str] = frozenset()
        # Tiles fetched (or being fetched) for coming frames that no frame has drawn yet.
        self.ahead: set[str] = set()
        self._fetching: dict[str, Future[TileResponse]] = {}
        self._lock = threading.Lock()
        self.size = 0
        self.clear()

    def __len__(self):
        return len(self.content)

    def clear(self):
        """Release a card's downloads and decoded images before the next card."""
        self.content.clear()
        self.images.clear()
        self.in_view = frozenset()
        self.ahead.clear()
        # Set once the tile host refuses, or a tile fails every attempt: the card stops
        # asking and its frames take the grey fallback instead of hammering the host.
        self.unreachable = False
        self.size = 0
        budget = memory_budget()
        self.limit = min(128 * 2**20, budget.size // 32) if budget else 32 * 2**20

    def release(self) -> None:
        """Release a finished card, but keep the downloads of the view it ended on.

        Consecutive location cards share that view (one lands where the next takes
        off), so the next card starts without fetching it again. Decoded pixels go.
        """
        kept = {url: self.content[url] for url in self.in_view if url in self.content}
        self.clear()
        self.content.update(kept)
        self.in_view = frozenset(kept)

    def fetch(self, url: str, download: Callable[[], TileResponse]) -> TileResponse:
        """One request for ``url`` at a time: a second caller waits for the first one's answer.

        A frame that needs a tile already on its way for a coming frame waits for that
        download instead of starting another; a stored download answers at once.
        """
        with self._lock:
            if url in self.content:
                return 200, self.content[url]
            if self.unreachable:
                return None, None
            pending = self._fetching.get(url)
            future: Future[TileResponse] = Future()
            if pending is None:
                self._fetching[url] = future
        if pending is not None:
            return pending.result()
        try:
            response = download()
        except BaseException as error:
            with self._lock:
                del self._fetching[url]
                # A refused connection answers the same a moment later; a reset or a
                # DNS hiccup may not, so those get the usual attempts.
                if _refused(error):
                    self.unreachable = True
            future.set_exception(error)
            raise
        with self._lock:
            status, content = response
            if status == 200 and content is not None:
                self.content[url] = content
            elif _refusal(status):
                self.unreachable = True
            del self._fetching[url]
        future.set_result(response)
        return response

    def reserve_ahead(self, url: str) -> bool:
        """Claim room to fetch ``url`` for a coming frame, within the decoded-tile budget."""
        with self._lock:
            if self.unreachable:
                return False
            if url in self.content or url in self._fetching or url in self.ahead:
                return False
            if (len(self.ahead) + 1) * _TILE_PIXEL_BYTES > self.limit:
                return False
            self.ahead.add(url)
            return True

    def give_up(self) -> None:
        """A tile failed every attempt: stop asking the host for the rest of the card."""
        with self._lock:
            self.unreachable = True

    def drawn(self, urls: Iterable[str]) -> None:
        """Hand the room of tiles fetched ahead back once a frame has drawn them."""
        with self._lock:
            self.ahead.difference_update(urls)

    def decode(self, url: str, content: bytes) -> Image.Image:
        """Reuse pixels while keeping their retained allocation within the budget."""
        if url in self.images:
            self.images.move_to_end(url)
            return self.images[url]
        with Image.open(io.BytesIO(content)) as source:
            # An opaque tile (every satellite JPEG) pastes without a mask: the same
            # pixels at a fifth of the cost, on hundreds of tiles a 4K frame.
            opaque = source.mode in _OPAQUE_MODES and "transparency" not in source.info
            image = source.convert("RGB" if opaque else "RGBA")
        size = _pixel_bytes(image)
        if size <= self.limit:
            while self.size + size > self.limit:
                _, old = self.images.popitem(last=False)
                self.size -= _pixel_bytes(old)
            self.images[url] = image
            self.size += size
        return image


def _refusal(status: int | None) -> bool:
    """A 4xx other than 429: asking again gets the same answer (a block, a wrong host)."""
    return status is not None and 400 <= status < 500 and status != 429


def _refused(error: BaseException) -> bool:
    """Whether the host turned the connection away, anywhere in the error's chain.

    The HTTP client wraps the socket's ConnectionRefusedError a few levels deep
    (through causes, contexts and a ``reason`` attribute), so it is looked for there.
    """
    seen: set[int] = set()
    pending: list[object] = [error]
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        if isinstance(current, ConnectionRefusedError):
            return True
        seen.add(id(current))
        pending += [current.__cause__, current.__context__, getattr(current, "reason", None)]
    return False


def _pixel_bytes(image: Image.Image) -> int:
    return image.width * image.height * len(image.getbands())


tile_cache = TileCache()


class CachedStaticMap(StaticMap):
    """StaticMap with shared downloaded bytes and decoded tiles across frames."""

    def _draw_features(self, image):
        # Pins and labels are drawn after fractional-zoom resizing. Empty features
        # otherwise allocate and resample an unused 2x RGBA surface.
        if self.markers or self.lines or self.polygons:
            super()._draw_features(image)

    def get(self, url: str, **kwargs):
        """Fetch through the download cache on a kept-alive connection, same request options."""
        return tile_cache.fetch(
            url, lambda: _download(url, kwargs.get("timeout"), kwargs.get("headers") or {})
        )

    def tile_urls(self, lon: float, lat: float, zoom: int) -> list[str]:
        """The tiles ``render(zoom, [lon, lat])`` draws, without drawing them."""
        self.zoom = zoom
        self.x_center = _lon_to_x(lon, zoom)
        self.y_center = _lat_to_y(lat, zoom)
        return [url for *_, url in self._tiles()]

    def _tiles(self):
        left = math.floor(self.x_center - self.width / (2 * self.tile_size))
        top = math.floor(self.y_center - self.height / (2 * self.tile_size))
        right = math.ceil(self.x_center + self.width / (2 * self.tile_size))
        bottom = math.ceil(self.y_center + self.height / (2 * self.tile_size))
        count = 2**self.zoom
        for x in range(left, right):
            for y in range(top, bottom):
                tile_y = y % count
                if self.reverse_y:
                    tile_y = count - tile_y - 1
                yield x, y, self.url_template.format(z=self.zoom, x=x % count, y=tile_y)

    def _paste(self, image, tile, content):
        x, y, url = tile
        pixels = tile_cache.decode(url, content)
        box = (self._x_to_px(x), self._y_to_px(y), self._x_to_px(x + 1), self._y_to_px(y + 1))
        image.paste(pixels, box, pixels if pixels.mode == "RGBA" else None)

    def _draw_base_layer(self, image):
        tiles = list(self._tiles())
        tile_cache.in_view = frozenset(url for *_, url in tiles)
        tile_cache.drawn(tile_cache.in_view)
        undecoded = []
        # Consume resident pixels first: a miss must not evict a tile this frame
        # still needs when the view is larger than the cache's memory budget.
        for tile in tiles:
            if tile[2] in tile_cache.images:
                self._paste(image, tile, tile_cache.content[tile[2]])
            else:
                undecoded.append(tile)
        missing = []
        for tile in undecoded:
            content = tile_cache.content.get(tile[2])
            if content is None:
                missing.append(tile)
            else:
                self._paste(image, tile, content)
        if missing:
            self._download_tiles(image, missing)

    def _download_tiles(self, image, missing):
        # Cold tiles retain StaticMap's four requests, three attempts and delay.
        with ThreadPoolExecutor(_FETCH_THREADS) as pool:
            for attempt in range(_FETCH_ATTEMPTS):
                if tile_cache.unreachable:
                    break
                if attempt and self.delay_between_retries:
                    time.sleep(self.delay_between_retries)
                missing = self._fetch_tiles(pool, image, missing)
                if not missing:
                    return
        tile_cache.give_up()
        # Avoid including URLs: they contain the camera's precise coordinates.
        raise RuntimeError(f"could not download {len(missing)} tiles")

    def _fetch_tiles(self, pool, image, missing):
        futures = [
            pool.submit(self.get, tile[2], timeout=self.request_timeout, headers=self.headers)
            for tile in missing
        ]
        failed = []
        for tile, future in zip(missing, futures, strict=True):
            try:
                status, content = future.result()
            except Exception:  # noqa: BLE001
                # A failed HTTP request is retried, like StaticMap's client.
                status, content = None, None
            if status != 200:
                failed.append(tile)
            else:
                self._paste(image, tile, content)
        return failed


class TilePrefetcher:
    """Fetches the tiles of a card's coming frames while the current frame renders.

    Same host, same request options and the same three attempts as a frame's own
    fetch. Room is claimed in the tile cache first, so what is fetched ahead and not
    yet drawn never outgrows its memory budget; a full cache simply waits for frames.
    """

    def __init__(self, renderer: CachedStaticMap) -> None:
        self._renderer = renderer
        self._pool = ThreadPoolExecutor(_FETCH_THREADS, thread_name_prefix="map-tiles")

    def __enter__(self) -> TilePrefetcher:
        return self

    def __exit__(self, *_exc: object) -> None:
        # A card that ends drops what it queued and waits out what is on the wire,
        # so nothing lands in the cache after the card has released it.
        self._pool.shutdown(wait=True, cancel_futures=True)
        tile_cache.ahead.clear()

    def ahead(self, urls: Iterable[str]) -> None:
        """Queue the tiles of a coming frame that are neither stored nor on their way."""
        for url in urls:
            if tile_cache.reserve_ahead(url):
                self._pool.submit(self._fetch, url)

    def _fetch(self, url: str) -> None:
        renderer = self._renderer
        for attempt in range(_FETCH_ATTEMPTS):
            if tile_cache.unreachable:
                break
            if attempt and renderer.delay_between_retries:
                time.sleep(renderer.delay_between_retries)
            try:
                status, _ = renderer.get(
                    url, timeout=renderer.request_timeout, headers=renderer.headers
                )
            except Exception:  # noqa: BLE001
                # A failed request is retried, like a frame's own fetch.
                status = None
            if status == 200:
                return
        # Out of attempts: the frame that needs it takes the fallback, and nothing more
        # is fetched ahead for this card.
        tile_cache.give_up()
        tile_cache.drawn([url])
