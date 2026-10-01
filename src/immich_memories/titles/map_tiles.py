"""Satellite tiles: retain downloads and a bounded working set of decoded pixels."""

from __future__ import annotations

import io
import math
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from staticmap import StaticMap

from immich_memories.processing.memory_budget import memory_budget


class TileCache:
    def __init__(self):
        self.content: dict[str, bytes] = {}
        self.images: OrderedDict[str, Image.Image] = OrderedDict()
        self.size = 0
        self.clear()

    def __len__(self):
        return len(self.content)

    def clear(self):
        """Release a card's downloads and decoded images before the next card."""
        self.content.clear()
        self.images.clear()
        self.size = 0
        budget = memory_budget()
        self.limit = min(128 * 2**20, budget.size // 32) if budget else 32 * 2**20

    def decode(self, url: str, content: bytes) -> Image.Image:
        """Reuse pixels while keeping their retained allocation within the budget."""
        if url in self.images:
            self.images.move_to_end(url)
            return self.images[url]
        with Image.open(io.BytesIO(content)) as source:
            image = source.convert("RGBA")
        size = image.width * image.height * 4
        if size <= self.limit:
            while self.size + size > self.limit:
                _, old = self.images.popitem(last=False)
                self.size -= old.width * old.height * 4
            self.images[url] = image
            self.size += size
        return image


tile_cache = TileCache()


class CachedStaticMap(StaticMap):
    """StaticMap with shared downloaded bytes and decoded tiles across frames."""

    def _draw_features(self, image):
        # Pins and labels are drawn after fractional-zoom resizing. Empty features
        # otherwise allocate and resample an unused 2x RGBA surface.
        if self.markers or self.lines or self.polygons:
            super()._draw_features(image)

    def get(self, url: str, **kwargs):
        """Keep the existing download cache and request options."""
        if url in tile_cache.content:
            return 200, tile_cache.content[url]
        status, content = super().get(url, **kwargs)
        if status == 200:
            tile_cache.content[url] = content
        return status, content

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
        image.paste(pixels, box, pixels)

    def _draw_base_layer(self, image):
        undecoded = []
        # Consume resident pixels first: a miss must not evict a tile this frame
        # still needs when the view is larger than the cache's memory budget.
        for tile in self._tiles():
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
        with ThreadPoolExecutor(4) as pool:
            for attempt in range(3):
                if attempt and self.delay_between_retries:
                    time.sleep(self.delay_between_retries)
                missing = self._fetch_tiles(pool, image, missing)
                if not missing:
                    return
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
