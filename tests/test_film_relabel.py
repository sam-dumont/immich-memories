"""A film already in Immich gets its label again without rendering it again (#2627)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from immich_memories.api import album_service
from immich_memories.api.album_service import AlbumService, UploadWaits, upload_waits
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.film_label import FilmLabel
from immich_memories.api.film_relabel import FilmRelabeler, RelabelStatus
from immich_memories.api.immich import ImmichNotFoundError
from immich_memories.api.permissions import ApiKeyCapabilities
from tests.immich_fakes import V3, request_problems

ASSET = "3f1c2a54-6b1e-4d0a-8a55-0d5c7a1b9e11"
PROVENANCE = "immich-memories/generated"
LABEL = FilmLabel(
    description="Monthly highlights · placeholder",
    tags=(
        "immich-memories/version/9.9.9",
        "immich-memories/generated-on/2026-01-02",
        "immich-memories/type/Monthly highlights",
        "immich-memories/year/2025",
    ),
)
# What an older release of the app, with another label format, left on the film.
OLD_TAGS = (
    "immich-memories/version/1.0.0",
    "immich-memories/type/Monthly highlights",
    "immich-memories/year/2024",
    "immich-memories/story/Old trip",
)
USER_TAGS = ("Family", "immich-memories-other/keep", "immich-memories/favourites")


class FakeImmich:
    """Immich as it answers a film delivered long ago: read once, then only our writes.

    Every request is checked against the Immich OpenAPI contract. `rereads_after` models
    Immich 3 reading a long film again after each write and putting back what it read when
    that read began.
    """

    def __init__(
        self,
        *,
        tags: tuple[str, ...] = (),
        description: str = "",
        gone: bool = False,
        modify_date: str | None = "2025-07-01",
        rereads_after: tuple[int, ...] = (),
    ) -> None:
        self.gone = gone
        self.modify_date = modify_date
        self.tag_ids: dict[str, str] = {}
        self.tags: set[str] = set()
        for value in tags:
            self.tags.add(value)
            self._id(value)
        self.description = description
        self.calls: list[tuple[str, str]] = []
        self.gets = 0
        self.updated = 0
        self.rereads_after = rereads_after
        self.rereads: list[tuple[int, set[str], str]] = []
        self.written = 0
        self.violations: list[str] = []

    def _id(self, value: str) -> str:
        n = len(self.tag_ids) + 1
        return self.tag_ids.setdefault(value, f"7a1d0c3e-5b2f-4e6a-9c8d-{n:012d}")

    def _wrote(self) -> None:
        self.updated += 1
        if self.rereads_after:
            delay = self.rereads_after[min(self.written, len(self.rereads_after) - 1)]
            self.rereads.append((self.gets + delay, set(self.tags), self.description))
        self.written += 1

    def _rereads_land(self) -> None:
        for reread in sorted((r for r in self.rereads if self.gets >= r[0]), key=lambda r: r[0]):
            self.rereads.remove(reread)
            self.tags, self.description = set(reread[1]), reread[2]
            self.updated += 1

    async def __call__(self, method: str, path: str, **kwargs):
        problems = request_problems(
            method, path, {}, kwargs.get("json"), uuid_ids=True, releases=V3
        )
        if problems:
            self.violations.extend(f"{method} {path}: {p}" for p in problems)
        self.calls.append((method, path))
        if (method, path) == ("GET", f"/assets/{ASSET}"):
            return self._get()
        if (method, path) == ("PUT", "/tags"):
            values = kwargs["json"]["tags"]
            return [{"id": self._id(v), "value": v} for v in values]
        if (method, path) == ("PUT", "/tags/assets"):
            by_id = {i: v for v, i in self.tag_ids.items()}
            self.tags.update(by_id[i] for i in kwargs["json"]["tagIds"])
            self._wrote()
            return {"count": 1}
        if method == "DELETE" and path.startswith("/tags/") and path.endswith("/assets"):
            by_id = {i: v for v, i in self.tag_ids.items()}
            self.tags.discard(by_id[path.split("/")[2]])
            self._wrote()
            return []
        if (method, path) == ("PUT", f"/assets/{ASSET}"):
            self.description = kwargs["json"]["description"]
            self._wrote()
            return {}
        pytest.fail(f"Unexpected request: {method} {path}")

    def _get(self) -> dict:
        if self.gone:
            raise ImmichNotFoundError("Resource not found", status_code=404)
        self.gets += 1
        self._rereads_land()
        return {
            "updatedAt": f"t{self.updated}",
            "exifInfo": {"modifyDate": self.modify_date, "description": self.description},
            "tags": [{"id": self._id(v), "value": v} for v in sorted(self.tags)],
        }


def _relabeler(immich: FakeImmich, *permissions: str) -> FilmRelabeler:
    capabilities = ApiKeyCapabilities(frozenset(permissions or {"all"}))
    api_version = AsyncMock(return_value=ResolvedApiVersion.V3)
    caps = AsyncMock(return_value=capabilities)
    return FilmRelabeler(AlbumService(immich, api_version, caps), immich, caps)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(album_service, "_POLL_SECONDS", 0)


@pytest.mark.asyncio
async def test_a_film_with_no_label_gets_the_description_and_tags():
    immich = FakeImmich()

    outcome = await _relabeler(immich).relabel(ASSET, LABEL, waits=UploadWaits())

    assert outcome.status is RelabelStatus.WRITTEN
    assert outcome.warnings == ()
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}
    assert immich.violations == []


@pytest.mark.asyncio
async def test_an_old_format_label_loses_its_stale_tags_and_user_tags_stay():
    immich = FakeImmich(tags=(PROVENANCE, *OLD_TAGS, *USER_TAGS), description="old title")

    outcome = await _relabeler(immich).relabel(ASSET, LABEL, waits=UploadWaits())

    assert outcome.status is RelabelStatus.WRITTEN
    assert set(outcome.removed) == {
        "immich-memories/version/1.0.0",
        "immich-memories/year/2024",
        "immich-memories/story/Old trip",
    }
    # The type tag is in both formats; nothing outside the app's root is ever touched.
    assert immich.tags == {PROVENANCE, *LABEL.tags, *USER_TAGS}
    assert immich.description == LABEL.description
    assert immich.violations == []


@pytest.mark.asyncio
async def test_a_label_that_already_matches_writes_nothing():
    immich = FakeImmich(tags=(PROVENANCE, *LABEL.tags, *USER_TAGS), description=LABEL.description)

    outcome = await _relabeler(immich).relabel(ASSET, LABEL, waits=UploadWaits())

    assert outcome.status is RelabelStatus.UNCHANGED
    assert [c for c in immich.calls if c[0] != "GET"] == []


@pytest.mark.asyncio
async def test_film_tags_turned_off_drops_the_old_type_year_and_story_tags():
    immich = FakeImmich(tags=(PROVENANCE, *LABEL.tags, "immich-memories/story/Old trip"))
    provenance_only = FilmLabel(description=LABEL.description, tags=LABEL.tags[:2])

    outcome = await _relabeler(immich).relabel(ASSET, provenance_only, waits=UploadWaits())

    assert outcome.status is RelabelStatus.WRITTEN
    assert immich.tags == {PROVENANCE, *LABEL.tags[:2]}


@pytest.mark.asyncio
async def test_a_film_gone_from_immich_is_refused_and_nothing_is_written():
    immich = FakeImmich(gone=True)

    outcome = await _relabeler(immich).relabel(ASSET, LABEL, waits=UploadWaits())

    assert outcome.status is RelabelStatus.ASSET_GONE
    assert [c for c in immich.calls if c[0] != "GET"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("lacking", ["tag.create", "tag.asset", "asset.update"])
async def test_a_key_without_the_rights_is_refused_naming_them(lacking):
    immich = FakeImmich(tags=(PROVENANCE, *OLD_TAGS))
    rights = {"tag.create", "tag.asset", "asset.update", "asset.read"} - {lacking}

    outcome = await _relabeler(immich, *rights).relabel(ASSET, LABEL, waits=UploadWaits())

    assert outcome.status is RelabelStatus.RIGHTS_MISSING
    assert lacking in outcome.detail
    assert [c for c in immich.calls if c[0] != "GET"] == []


@pytest.mark.asyncio
async def test_a_long_films_slow_reread_does_not_take_the_new_label_back():
    # WHY: Immich 3 reads a 1 GB film again after each write, slowly, and the late read puts
    # back what the asset held when it began; the waits grow with the stored film size.
    immich = FakeImmich(
        tags=(PROVENANCE, *OLD_TAGS), description="old title", rereads_after=(40, 6)
    )

    outcome = await _relabeler(immich).relabel(ASSET, LABEL, waits=upload_waits(1_000_000_000))
    immich.gets += 1_000  # every re-read Immich queued has landed by now
    await immich("GET", f"/assets/{ASSET}")

    assert outcome.status is RelabelStatus.WRITTEN
    assert outcome.warnings == ()
    assert immich.description == LABEL.description
    assert immich.tags == {PROVENANCE, *LABEL.tags}


@pytest.mark.asyncio
async def test_an_old_film_with_no_read_stamp_is_not_reported_as_not_kept():
    # WHY: `apply_label_once_read` waits for Immich's first read of a fresh upload and, when
    # none shows, reports every field as not kept. A film delivered long ago has been read; one
    # whose exif never carried a modify date must not wait a quarter of an hour, nor misreport.
    immich = FakeImmich(modify_date=None)

    outcome = await _relabeler(immich).relabel(
        ASSET, LABEL, waits=UploadWaits(read_polls=1800, quiet_polls=4)
    )

    assert outcome.status is RelabelStatus.WRITTEN
    assert outcome.warnings == ()
    assert immich.description == LABEL.description
    # Nothing polled for the first read: a handful of reads, not 1800.
    assert immich.gets < 200
