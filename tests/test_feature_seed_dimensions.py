"""The feature seed edits a picture only once Immich has read its width and height (#2883).

Immich's editor refuses an asset without dimensions ("Asset dimensions are not available for
editing"), and its queues can report empty while one asset still has none.
"""

import httpx
import pytest

from tests.immich_fakes import ImmichWire
from tests.integration.features import real_seed
from tests.integration.immich_gate.seed import Seeder, SeedError

ASSET = "0b6f4c1e-7d2a-4e8b-9c3f-5a1d2e3f4b6c"


def immich_reading(dimensions_after: int):
    """An Immich whose metadata pass writes the asset's dimensions on the n-th read."""
    reads: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/server/version":
            return httpx.Response(200, json={"major": 2, "minor": 0, "patch": 0})
        assert request.url.path == f"/api/assets/{ASSET}"
        reads.append(request.method)
        known = len(reads) >= dimensions_after
        return httpx.Response(
            200,
            json={"id": ASSET, "width": 4032 if known else None, "height": 3024 if known else None},
        )

    return ImmichWire(serve), reads


def test_the_seed_waits_until_immich_has_read_the_dimensions(monkeypatch):
    wire, reads = immich_reading(dimensions_after=3)
    seeder = Seeder("http://immich.invalid", "key", transport=wire.transport)
    # WHY: the poll interval is wall-clock time; the fake answers instantly.
    monkeypatch.setattr(real_seed.time, "sleep", lambda _seconds: None)

    real_seed.wait_for_dimensions(seeder, ASSET, "lake-edited.jpg")

    assert reads == ["GET", "GET", "GET"]
    wire.assert_clean()


def test_dimensions_that_never_arrive_fail_the_seed_naming_the_fixture():
    wire, _reads = immich_reading(dimensions_after=99)
    seeder = Seeder("http://immich.invalid", "key", transport=wire.transport)

    with pytest.raises(SeedError, match=r"lake-edited\.jpg"):
        real_seed.wait_for_dimensions(seeder, ASSET, "lake-edited.jpg", timeout=0)
    wire.assert_clean()
