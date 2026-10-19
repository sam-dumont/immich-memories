"""An uploaded film gets its description and tags once Immich has read it (#2505)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from immich_memories.api import album_service
from immich_memories.api.album_service import AlbumService
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.film_label import FilmLabel
from immich_memories.api.permissions import ApiKeyCapabilities

PROVENANCE = "immich-memories/generated"
LABEL = FilmLabel(
    description="July 2025 · Kit's birthday",
    tags=("immich-memories/type/Monthly highlights", "immich-memories/year/2025"),
)


class FakeImmich:
    """Just enough of Immich: an upload, a metadata read that wipes what came before it."""

    def __init__(
        self,
        *,
        reads_after: int = 2,
        sticks: bool = True,
        sidecar_after: int = 0,
        rereads_after: tuple[int, ...] = (),
    ) -> None:
        self.reads_after = reads_after
        self.sticks = sticks
        self.gets = 0
        self.read = False
        self.tag_ids: dict[str, str] = {}
        self.tags: set[str] = set()
        self.description = ""
        self.writes: list[tuple[str, str]] = []
        # Immich writes the sidecar after each tag or description write and reads it back
        # `sidecar_after` reads later. Writes that overlap collide, and the read-back restores
        # what the first of them wrote (an exiftool rename error in Immich's log).
        self.sidecar_after = sidecar_after
        self.sidecar: tuple[int, set[str], str] | None = None
        # Immich 3 reads the whole film again after each write (sidecar write, then a metadata
        # job whose ffprobe scans every packet). The job reads the sidecar as it starts and
        # writes what it read when it ends, `rereads_after[n]` reads after the n-th write; it
        # leaves the asset untouched until then. A cold first read of a long film is the
        # slowest, so a stale read can land after a later one.
        self.rereads_after = rereads_after
        self.rereads: list[tuple[int, set[str], str]] = []
        self.written = 0
        self.updated = 0

    def _wrote(self) -> None:
        self.updated += 1
        if self.rereads_after:
            delay = self.rereads_after[min(self.written, len(self.rereads_after) - 1)]
            self.rereads.append((self.gets + delay, set(self.tags), self.description))
        self.written += 1
        if self.sidecar_after and self.read and self.sidecar is None:
            self.sidecar = (self.gets + self.sidecar_after, set(self.tags), self.description)

    def _rereads_land(self) -> None:
        landed = sorted((r for r in self.rereads if self.gets >= r[0]), key=lambda r: r[0])
        for reread in landed:
            self.rereads.remove(reread)
            _, self.tags, self.description = reread[0], set(reread[1]), reread[2]
            self.updated += 1

    def _sidecar_read_back(self) -> None:
        if self.sidecar is not None and self.gets >= self.sidecar[0]:
            _, self.tags, self.description = self.sidecar
            self.sidecar = None
            self.updated += 1

    async def __call__(self, method: str, path: str, **kwargs):
        if (method, path) == ("POST", "/assets"):
            return {"id": "film"}
        if (method, path) == ("GET", "/assets/film"):
            self.gets += 1
            if not self.read and self.gets > self.reads_after:
                # Immich's own metadata job: it ends by overwriting the asset's tags and description.
                self.read = True
                self.tags.clear()
                self.description = ""
            self._sidecar_read_back()
            self._rereads_land()
            return {
                "updatedAt": f"t{self.updated}",
                "exifInfo": {
                    "modifyDate": "2025-07-01" if self.read else None,
                    "description": self.description,
                },
                "tags": [{"value": value} for value in sorted(self.tags)],
            }
        if (method, path) == ("PUT", "/tags"):
            self.writes.append((method, path))
            values = kwargs["json"]["tags"]
            for value in values:
                self.tag_ids.setdefault(value, f"id-{len(self.tag_ids)}")
            return [{"id": self.tag_ids[value], "value": value} for value in values]
        if (method, path) == ("PUT", "/tags/assets"):
            self.writes.append((method, path))
            if self.sticks:
                by_id = {i: v for v, i in self.tag_ids.items()}
                self.tags.update(by_id[i] for i in kwargs["json"]["tagIds"])
            self._wrote()
            return {"count": 1}
        if method == "PUT" and path.startswith("/tags/") and path.endswith("/assets"):
            self.writes.append((method, path))
            value = next(v for v, i in self.tag_ids.items() if i == path.split("/")[2])
            if self.sticks:
                self.tags.add(value)
            self._wrote()
            return []
        if (method, path) == ("PUT", "/assets/film"):
            self.writes.append((method, path))
            if self.sticks:
                self.description = kwargs["json"]["description"]
            self._wrote()
            return {}
        pytest.fail(f"Unexpected request: {method} {path}")


def _service(immich: FakeImmich, *permissions: str) -> AlbumService:
    capabilities = (
        ApiKeyCapabilities(frozenset(permissions))
        if permissions
        else ApiKeyCapabilities(frozenset({"all"}))
    )
    return AlbumService(
        immich,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(return_value=capabilities),
    )


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(album_service, "_POLL_SECONDS", 0)


@pytest.fixture
def film(tmp_path: Path) -> Path:
    path = tmp_path / "film.mp4"
    path.write_bytes(b"film")
    return path


@pytest.mark.asyncio
async def test_description_and_tags_survive_immichs_own_read(film):
    immich = FakeImmich(reads_after=3)

    result = await _service(immich).upload_memory(film, label=LABEL)

    assert result["warnings"] == []
    assert result["delivery_complete"] is True
    assert immich.read
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}


@pytest.mark.asyncio
async def test_every_tag_survives_immich_reading_its_sidecar_back(film):
    # WHY: one write per tag made Immich write the film's sidecar once per tag; the writes
    # collided and the read-back dropped the story tag after our check had passed.
    immich = FakeImmich(reads_after=1, sidecar_after=3)

    result = await _service(immich).upload_memory(film, label=LABEL)

    assert result["warnings"] == []
    assert immich.sidecar is None
    assert immich.tags == {PROVENANCE, *LABEL.tags}
    assert immich.description == LABEL.description
    assert immich.writes.count(("PUT", "/tags/assets")) == 1


@pytest.mark.asyncio
async def test_a_label_that_did_not_stick_is_applied_again_then_warns(film):
    immich = FakeImmich(sticks=False)

    result = await _service(immich).upload_memory(film, label=LABEL)

    # Nothing sticks here, the provenance tag included: that one does make it incomplete.
    assert result["delivery_complete"] is False
    assert any("description" in w and "did not stay" in w for w in result["warnings"])
    assert any("tags" in w and "did not stay" in w for w in result["warnings"])
    assert sum(1 for write in immich.writes if write == ("PUT", "/assets/film")) > 1


@pytest.mark.asyncio
async def test_a_key_without_asset_update_uploads_with_tags_and_warns(film):
    immich = FakeImmich()
    # A key made before films had labels: it can still replace the film's earlier render.
    permissions = (
        "asset.upload",
        "asset.delete",
        "tag.create",
        "tag.asset",
        "album.create",
        "albumAsset.create",
    )

    result = await _service(immich, *permissions).upload_memory(film, label=LABEL)

    assert result["asset_id"] == "film"
    assert result["delivery_complete"] is True
    assert not any("previous version kept" in w for w in result["warnings"])
    assert "asset.update" in result["missing_permissions"]
    assert any("description" in w and "asset.update" in w for w in result["warnings"])
    assert ("PUT", "/assets/film") not in immich.writes
    assert set(LABEL.tags) <= immich.tags


@pytest.mark.asyncio
async def test_a_key_without_tag_rights_still_sets_the_description(film):
    immich = FakeImmich()

    result = await _service(immich, "asset.upload", "asset.update").upload_memory(film, label=LABEL)

    assert result["asset_id"] == "film"
    assert immich.description == LABEL.description
    assert immich.tags == set()
    assert any("tag.create" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_a_label_with_nothing_to_say_asks_immich_for_nothing(film):
    immich = FakeImmich()

    result = await _service(immich).upload_memory(film, label=FilmLabel())

    assert result["warnings"] == []
    assert immich.description == ""
    assert immich.tags == {PROVENANCE}


@pytest.mark.asyncio
async def test_a_failing_label_step_keeps_the_upload_and_leaves_the_delivery_pending(film):
    immich = FakeImmich()
    plain = immich.__call__

    async def request(method, path, **kwargs):
        if (method, path) == ("PUT", "/assets/film"):
            raise RuntimeError("boom")
        return await plain(method, path, **kwargs)

    service = AlbumService(
        request,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(return_value=ApiKeyCapabilities(frozenset({"all"}))),
    )
    result = await service.upload_memory(film, label=LABEL)

    assert result["asset_id"] == "film"
    # Pending, so the delivery retry labels it again (#2540).
    assert result["delivery_complete"] is False
    assert not result["missing_permissions"]
    assert any("boom" in w for w in result["warnings"])


# --- A long film's late metadata read (#2540) ------------------------------------------------


@pytest.fixture
def year_film(tmp_path: Path) -> Path:
    """A 1 GB film, as a ten-minute year film is; sparse, so it costs no disk."""
    path = tmp_path / "year.mp4"
    with path.open("wb") as handle:
        handle.truncate(1_000_000_000)
    return path


@pytest.mark.asyncio
async def test_a_long_film_keeps_its_description_when_immich_reads_it_late(year_film):
    # WHY: a 1 GB film was read after the fixed minute's wait (120 polls); the read wiped the
    # description written before it, and the upload counted as complete.
    immich = FakeImmich(reads_after=400)

    result = await _service(immich).upload_memory(year_film, label=LABEL)
    # Immich's read has landed by now, whenever it was queued.
    immich.reads_after = min(immich.reads_after, immich.gets)
    await immich("GET", "/assets/film")

    assert result["warnings"] == []
    assert result["delivery_complete"] is True
    assert immich.read
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}


@pytest.mark.asyncio
async def test_a_read_later_still_leaves_the_delivery_pending_and_the_retry_labels_it(film):
    immich = FakeImmich(reads_after=10_000)

    first = await _service(immich).upload_memory(film, label=LABEL)

    assert first["delivery_complete"] is False
    assert not first["missing_permissions"]
    assert any("description" in w and "did not stay" in w for w in first["warnings"])

    immich.reads_after = immich.gets  # Immich reads the film at last, wiping the label
    await immich("GET", "/assets/film")
    assert immich.description == ""

    retry = await _service(immich).upload_memory(film, label=LABEL)

    assert retry["delivery_complete"] is True
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}


# --- Immich reading a long film again after each write (#2540 again) -------------------------


@pytest.mark.asyncio
async def test_a_long_film_keeps_its_label_when_immich_reads_it_again_slowly(year_film):
    # WHY: on Immich 3 every tag or description write makes Immich read the film again, and a
    # 1 GB film takes longer to read than the two quiet seconds we called settled. The first,
    # cold re-read (after the provenance tag) landed after the label was written and checked,
    # and put back the asset as it was then: no description, only the provenance tag.
    immich = FakeImmich(reads_after=1, rereads_after=(40, 6))

    result = await _service(immich).upload_memory(year_film, label=LABEL)
    # Every re-read Immich queued has landed by now.
    immich.gets += 1_000
    await immich("GET", "/assets/film")

    assert result["warnings"] == []
    assert result["delivery_complete"] is True
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}


# --- One write per kind, so one quiet wait fewer (#2711) --------------------------------------


@pytest.mark.asyncio
async def test_the_provenance_tag_rides_in_the_story_tags_write(film):
    # WHY: each write makes Immich rewrite the film's sidecar, and each is waited out on its
    # own. The provenance tag written on its own cost a whole wait before the label's own.
    immich = FakeImmich(reads_after=1)

    result = await _service(immich).upload_memory(film, label=LABEL)

    assert result["warnings"] == []
    assert result["delivery_complete"] is True
    assert immich.tags == {PROVENANCE, *LABEL.tags}
    assert immich.writes == [("PUT", "/tags"), ("PUT", "/tags/assets"), ("PUT", "/assets/film")]


@pytest.mark.asyncio
async def test_a_film_whose_provenance_did_not_stay_says_so(film):
    immich = FakeImmich(sticks=False)

    result = await _service(immich).upload_memory(film, label=LABEL)

    assert any("provenance" in w and "did not stay" in w for w in result["warnings"])
