"""Preview and face reads run a bounded few at a time, with the same files and rows (#2711).

Each picture costs Immich one preview read, and one more for its faces. One at a time, a cold
year waits through every request's latency in turn. These tests prove the reads overlap, stay
within the bound, cost exactly one request per picture, and leave the same cache and bank.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from immich_memories.analysis.facts.subject_framing import FaceBox
from immich_memories.api.immich import ImmichAPIError
from immich_memories.db.tables import face_boxes
from tests.annotation_rows import annotation_store, read_rows
from tests.test_editorial_preparation import asset, preview, run, successful_ports

_IDS = tuple(f"a{n:02d}" for n in range(12))


class _Immich:
    """WHY: stands in for Immich's preview and face endpoints; counts requests and how many
    are in flight at once. A barrier makes the first `workers` reads wait for each other, so
    a strictly serial caller fails it instead of passing by luck."""

    def __init__(self, workers: int, *, refuse: frozenset[str] = frozenset()) -> None:
        self._lock = threading.Lock()
        self._barrier = threading.Barrier(workers, timeout=10)
        self._refuse = refuse
        self.requests: list[str] = []
        self.in_flight = 0
        self.most_in_flight = 0

    def _enter(self, request: str) -> None:
        with self._lock:
            self.requests.append(request)
            self.in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self.in_flight)
            first_wave = len(self.requests) <= self._barrier.parties
        if first_wave:
            self._barrier.wait()

    def _leave(self) -> None:
        with self._lock:
            self.in_flight -= 1

    def preview(self, asset_id: str) -> bytes:
        self._enter(f"preview:{asset_id}")
        try:
            if asset_id in self._refuse:
                raise ImmichAPIError("no preview", status_code=404)
            return preview()
        finally:
            self._leave()

    def faces(self, asset_id: str):
        self._enter(f"faces:{asset_id}")
        try:
            return (FaceBox(x1=0.2, y1=0.2, x2=0.5, y2=0.6, named=True, person_id="p"),)
        finally:
            self._leave()


def _cached(root: Path, asset_id: str) -> Path:
    return root / asset_id[:2] / f"{asset_id}_preview.jpg"


def _digests(root: Path) -> dict[str, str]:
    return {
        asset_id: hashlib.sha256(_cached(root, asset_id).read_bytes()).hexdigest()
        for asset_id in _IDS
        if _cached(root, asset_id).exists()
    }


def _prepare(tmp_path: Path, immich: _Immich, workers: int):
    return run(
        tmp_path,
        assets=[asset(asset_id) for asset_id in _IDS],
        ports=successful_ports([]),
        fetch_preview=immich.preview,
        fetch_faces=immich.faces,
        read_workers=workers,
    )


def test_previews_and_faces_overlap_within_the_bound_one_request_per_picture(tmp_path):
    immich = _Immich(workers=3)

    result = _prepare(tmp_path / "concurrent", immich, workers=3)

    assert result.complete
    assert immich.most_in_flight == 3
    assert sorted(immich.requests) == sorted(
        [f"preview:{a}" for a in _IDS] + [f"faces:{a}" for a in _IDS]
    )


def test_concurrent_reads_leave_the_same_previews_and_face_rows_as_one_at_a_time(tmp_path):
    serial_root, concurrent_root = tmp_path / "serial", tmp_path / "concurrent"
    _prepare(serial_root, _Immich(workers=1), workers=1)
    serial_faces = sorted(read_rows(annotation_store(), face_boxes), key=str)

    _prepare(concurrent_root, _Immich(workers=4), workers=4)

    assert _digests(concurrent_root / "previews") == _digests(serial_root / "previews")
    assert len(_digests(serial_root / "previews")) == len(_IDS)
    assert sorted(read_rows(annotation_store(), face_boxes), key=str) == serial_faces


def test_a_warm_rerun_makes_no_request(tmp_path):
    _prepare(tmp_path, _Immich(workers=3), workers=3)
    warm = _Immich(workers=1)

    _prepare(tmp_path, warm, workers=3)

    assert warm.requests == []


@pytest.mark.parametrize("workers", [1, 3])
def test_a_picture_immich_has_no_preview_for_is_excluded_either_way(tmp_path, workers):
    immich = _Immich(workers=workers, refuse=frozenset({"a05"}))

    result = _prepare(tmp_path, immich, workers=workers)

    assert set(result.unservable_sources) == {"a05"}
    assert not _cached(tmp_path / "previews", "a05").exists()


class _Client:
    """WHY: stands in for the run's Immich client; records which clients each thread opens
    and closes, which is what keeps threads from queueing on one connection."""

    def __init__(self, opened: list[_Client]) -> None:
        self._opened = opened
        self.closed = False

    def sibling(self) -> _Client:
        sibling = _Client(self._opened)
        self._opened.append(sibling)
        return sibling

    def close(self) -> None:
        self.closed = True


def test_each_worker_thread_reads_through_its_own_client_and_all_are_closed():
    from immich_memories.analysis.preparation.bounded_reads import ThreadClients, read_each

    opened: list[_Client] = []
    run_client = _Client(opened)
    clients = ThreadClients(run_client)
    barrier = threading.Barrier(3, timeout=10)

    def read(_asset_id: str) -> _Client:
        barrier.wait()
        return clients.current()

    answers = list(read_each(("a", "b", "c"), read, workers=3, check=lambda: None))
    clients.close()

    used = {id(client) for _, client, _ in answers}
    assert len(used) == 3
    assert run_client not in [client for _, client, _ in answers]
    assert clients.current() is run_client
    assert len(opened) == 3
    assert all(client.closed for client in opened)
    assert not run_client.closed


def test_a_sync_client_s_sibling_reaches_the_same_server_with_its_own_connections():
    from immich_memories.api.immich import SyncImmichClient

    with SyncImmichClient(base_url="http://immich.test", api_key="key", api_version="v2") as run:
        sibling = run.sibling()

    assert (sibling.base_url, sibling.api_key, sibling.timeout) == (
        run.base_url,
        run.api_key,
        run.timeout,
    )
    assert sibling._async_client is not run._async_client
    sibling.close()
