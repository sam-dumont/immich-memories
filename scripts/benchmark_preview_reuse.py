"""Measure bounded decoded-preview reuse under the existing stage-by-stage order.

This diagnostic does not change production decoding or claim a preparation speedup.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import statistics
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image


def decode(payload):
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


def replay(payloads, capacity):
    cache = OrderedDict()
    decoded = hits = retained = peak = 0
    output = hashlib.sha256()
    started = time.perf_counter()
    # Producers traverse their pending cohort in separate passes today.
    for _ in range(3):
        for index, payload in enumerate(payloads):
            if index in cache:
                image = cache.pop(index)
                hits += 1
            else:
                image = decode(payload)
                decoded += 1
                retained += image.width * image.height * 3
            output.update(str((image.size, image.getpixel((0, 0)))).encode())
            if capacity:
                cache[index] = image
                while len(cache) > capacity:
                    _, evicted = cache.popitem(last=False)
                    retained -= evicted.width * evicted.height * 3
                    evicted.close()
            else:
                retained -= image.width * image.height * 3
                image.close()
            peak = max(peak, retained)
    elapsed = time.perf_counter() - started
    for image in cache.values():
        image.close()
    return {
        "seconds": elapsed,
        "decodes": decoded,
        "hits": hits,
        "retained_rgb_bytes": peak,
        "sample_digest": output.hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--assets", type=int, default=96)
    parser.add_argument("--capacity", type=int, default=16)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if min(args.assets, args.capacity, args.repeat) < 1:
        parser.error("assets, capacity and repeat must be positive")
    fixtures = sorted(
        {p.read_bytes() for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"}}
    )
    if not fixtures:
        parser.error("no JPEG fixtures")
    payloads = [fixtures[i % len(fixtures)] for i in range(args.assets)]
    expected = None
    for capacity in (0, args.capacity, args.assets):
        runs = [replay(payloads, capacity) for _ in range(args.repeat)]
        digests = {r["sample_digest"] for r in runs}
        expected = expected or digests
        assert digests == expected
        print(
            json.dumps(
                {
                    "assets": args.assets,
                    "capacity": capacity,
                    "median_seconds": statistics.median(r["seconds"] for r in runs),
                    "runs": runs,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
