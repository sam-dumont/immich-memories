"""Exact preview reuse must survive process restarts without trusting stale asset IDs."""

import sqlite3

import cv2
import numpy as np
import pytest

from immich_memories.analysis.corpus.duplicate_hashing import compute_thumbnail_hash
from immich_memories.analysis.preparation import thumbnail_hashes as module
from immich_memories.analysis.preparation.thumbnail_hashes import CachedThumbnailHasher


def preview(reverse=False):
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    pixels[32 if reverse else 0 : 64 if reverse else 32] = 255
    ok, encoded = cv2.imencode(".jpg", pixels)
    assert ok
    return encoded.tobytes()


def test_restart_reuses_exact_bytes_without_decoding_and_changed_bytes_miss(tmp_path, monkeypatch):
    payloads = {"same-id": preview()}
    path = tmp_path / "hashes.sqlite"
    first = CachedThumbnailHasher(path, payloads.get)
    expected = compute_thumbnail_hash(payloads["same-id"])
    assert first("same-id") == expected
    first.close()
    decoded = []

    def count(payload, size):
        decoded.append(payload)
        return compute_thumbnail_hash(payload, size)

    monkeypatch.setattr(module, "compute_thumbnail_hash", count)
    second = CachedThumbnailHasher(path, payloads.get)
    try:
        assert second("same-id") == expected
        assert decoded == []
        payloads["same-id"] = preview(reverse=True)
        assert second("same-id") == compute_thumbnail_hash(payloads["same-id"]) != expected
        assert len(decoded) == 1
        assert second.metrics()["cache_hits"] == 1
        assert second.metrics()["hashes_computed"] == 1
    finally:
        second.close()


@pytest.mark.parametrize("changed", ["size", "method"])
def test_hash_implementation_and_size_are_part_of_identity(tmp_path, monkeypatch, changed):
    path = tmp_path / "hashes.sqlite"
    payload = preview()
    first = CachedThumbnailHasher(path, lambda _asset: payload)
    first("a")
    first.close()
    if changed == "method":
        monkeypatch.setattr(module, "METHOD", "next-producer-version")
    second = CachedThumbnailHasher(
        path, lambda _asset: payload, hash_size=16 if changed == "size" else 8
    )
    try:
        second("a")
        assert second.metrics()["hashes_computed"] == 1
        assert second.metrics()["cache_hits"] == 0
    finally:
        second.close()


def test_identical_previews_can_share_a_fact_across_asset_ids(tmp_path):
    hasher = CachedThumbnailHasher(tmp_path / "hashes.sqlite", lambda _asset: preview())
    try:
        assert hasher("a") == hasher("b")
        assert hasher.metrics()["hashes_computed"] == 1
        assert hasher.metrics()["cache_hits"] == 1
    finally:
        hasher.close()


def test_unavailable_or_unreadable_previews_are_never_banked_as_valid_hashes(tmp_path):
    payloads = {}
    path = tmp_path / "hashes.sqlite"
    hasher = CachedThumbnailHasher(path, payloads.get)
    try:
        assert hasher("a") is None
        payloads["a"] = b"not an image"
        assert hasher("a") is None
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM thumbnail_hashes").fetchone()[0] == 0
        payloads["a"] = preview()
        assert hasher("a") == compute_thumbnail_hash(payloads["a"])
        assert hasher.metrics()["cache_hits"] == 0
    finally:
        hasher.close()


def test_sqlite_corruption_stops_the_campaign_instead_of_silently_recomputing(tmp_path):
    path = tmp_path / "hashes.sqlite"
    path.write_bytes(b"corrupt database")
    hasher = CachedThumbnailHasher(path, lambda _asset: preview())
    try:
        with pytest.raises(sqlite3.DatabaseError):
            hasher("a")
    finally:
        hasher.close()


def test_cached_fingerprint_does_not_copy_the_entire_preview(tmp_path):
    import tracemalloc

    payload = preview() + bytes(2 * 1024 * 1024)
    hasher = CachedThumbnailHasher(tmp_path / "hashes.sqlite", lambda _: payload)
    try:
        expected = hasher("picture")
        assert expected is not None
        tracemalloc.start()
        try:
            assert hasher("picture") == expected
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < len(payload) // 2
        assert hasher.metrics()["cache_hits"] == 1
    finally:
        hasher.close()


def test_streamed_fingerprint_keeps_the_existing_persistent_key(tmp_path):
    import hashlib

    payload = preview()
    path = tmp_path / "hashes.sqlite"
    hasher = CachedThumbnailHasher(path, lambda _: payload, hash_size=16)
    try:
        expected = hasher("picture")
    finally:
        hasher.close()
    legacy_key = hashlib.sha256(f"{module.METHOD}\0{16}\0".encode() + payload).hexdigest()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT source_key, thumbnail_hash FROM thumbnail_hashes"
        ).fetchall() == [(legacy_key, expected)]


def _distinct_previews(count):
    previews = {}
    for index in range(count):
        pixels = np.full((64, 64, 3), index * 40 % 256, dtype=np.uint8)
        pixels[: 8 * (index + 1)] = 255 - index * 40 % 256
        ok, encoded = cv2.imencode(".jpg", pixels)
        assert ok
        previews[f"asset-{index}"] = encoded.tobytes()
    return previews


@pytest.fixture
def statements(monkeypatch):
    """Every SQL statement the hasher's connections run, in order."""
    from immich_memories.cache import sqlite_conn

    seen: list[str] = []
    real = sqlite_conn.connect_sqlite

    def tracing(*args, **kwargs):
        connection = real(*args, **kwargs)
        connection.set_trace_callback(seen.append)
        return connection

    # WHY: counts what reaches SQLite; the connections stay real.
    monkeypatch.setattr(sqlite_conn, "connect_sqlite", tracing)
    return seen


def _count(statements, verb):
    return sum(statement.lstrip().upper().startswith(verb) for statement in statements)


def test_the_refinement_pass_hashes_nothing_the_draft_already_hashed(tmp_path, statements):
    """A film builds its material twice, draft then refinement, each with its own hasher."""
    previews = _distinct_previews(5)
    path = tmp_path / "hashes.sqlite"
    draft = CachedThumbnailHasher(path, previews.get)
    drafted = {asset_id: draft(asset_id) for asset_id in previews}
    statements.clear()

    refinement = CachedThumbnailHasher(path, previews.get)
    try:
        refined = {asset_id: refinement(asset_id) for asset_id in previews}
    finally:
        refinement.close()
        draft.close()

    assert refined == drafted
    assert len(set(refined.values())) == 5
    assert refinement.metrics()["hashes_computed"] == 0
    assert refinement.metrics()["cache_hits"] == 5
    assert _count(statements, "SELECT") == 0


def test_a_preview_that_changed_is_hashed_again_not_answered_from_memory(tmp_path):
    previews = {"a": preview()}
    path = tmp_path / "hashes.sqlite"
    draft = CachedThumbnailHasher(path, previews.get)
    before = draft("a")
    previews["a"] = preview(reverse=True)
    refinement = CachedThumbnailHasher(path, previews.get)
    try:
        after = refinement("a")
    finally:
        refinement.close()
        draft.close()

    assert after == compute_thumbnail_hash(previews["a"]) != before
    assert refinement.metrics()["hashes_computed"] == 1


def test_a_cold_pool_is_banked_in_one_commit_and_survives_a_restart(tmp_path, statements):
    previews = _distinct_previews(5)
    path = tmp_path / "hashes.sqlite"
    hasher = CachedThumbnailHasher(path, previews.get)
    hashed = {asset_id: hasher(asset_id) for asset_id in previews}
    hasher.close()

    assert _count(statements, "COMMIT") == 1
    with sqlite3.connect(path) as connection:
        banked = connection.execute("SELECT thumbnail_hash FROM thumbnail_hashes").fetchall()
    assert sorted(value for (value,) in banked) == sorted(hashed.values())
