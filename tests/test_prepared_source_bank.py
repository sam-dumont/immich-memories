"""The prepared-source bank: verified reuse, damaged entries, the size cap, two writers."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from immich_memories.cache.prepared_source_bank import PreparedSourceBank

KEY_A = "a" * 64
KEY_B = "b" * 64
KEY_C = "c" * 64


def _media(directory: Path, name: str, payload: bytes) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _bank(tmp_path: Path, max_bytes: int = 10_000_000) -> PreparedSourceBank:
    return PreparedSourceBank(tmp_path / "bank", max_bytes=max_bytes)


def test_a_kept_preparation_comes_back_as_the_callers_own_file(tmp_path):
    bank = _bank(tmp_path)
    fresh = _media(tmp_path / "run1", "clip.mp4", b"prepared bytes")
    bank.keep(KEY_A, fresh, {"duration": 2.5})

    taken = bank.take(KEY_A, destination=lambda _facts: tmp_path / "run2" / "again.mp4")

    assert taken is not None
    assert taken.path == tmp_path / "run2" / "again.mp4"
    assert taken.path.read_bytes() == b"prepared bytes"
    assert taken.facts == {"duration": 2.5}
    # The run's copy outlives the bank entry: a later eviction cannot pull it away.
    for entry in (tmp_path / "bank").rglob("*.mp4"):
        entry.unlink()
    assert taken.path.read_bytes() == b"prepared bytes"


def test_an_unknown_key_is_a_miss(tmp_path):
    bank = _bank(tmp_path)

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4") is None
    assert not (tmp_path / "out.mp4").exists()


def test_a_damaged_entry_is_dropped_and_never_handed_out(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "clip.mp4", b"x" * 4096), {"duration": 1.0})
    (banked,) = (tmp_path / "bank").rglob("*.mp4")
    with banked.open("r+b") as handle:  # a flipped byte, same size
        handle.seek(100)
        handle.write(b"y")

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4") is None
    assert not (tmp_path / "out.mp4").exists()
    assert list((tmp_path / "bank").rglob("*.mp4")) == []


def test_a_truncated_entry_is_dropped(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "clip.mp4", b"x" * 4096), {"duration": 1.0})
    (banked,) = (tmp_path / "bank").rglob("*.mp4")
    os.truncate(banked, 1000)

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4") is None


def test_a_record_without_its_media_is_a_miss(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "clip.mp4", b"bytes"), {"duration": 1.0})
    for media in (tmp_path / "bank").rglob("*.mp4"):
        media.unlink()

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4") is None


def test_an_unreadable_record_is_a_miss(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "clip.mp4", b"bytes"), {"duration": 1.0})
    (record,) = (tmp_path / "bank").rglob("*.json")
    record.write_text("{not json")

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4") is None


def test_a_rejected_entry_is_not_materialised(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "clip.mp4", b"bytes"), {"duration": 1.0})

    taken = bank.take(
        KEY_A, destination=lambda _facts: tmp_path / "out.mp4", accept=lambda _facts: False
    )

    assert taken is None
    assert not (tmp_path / "out.mp4").exists()


def test_eviction_drops_the_least_recently_used_entries_first(tmp_path):
    bank = _bank(tmp_path, max_bytes=2500)
    for key in (KEY_A, KEY_B, KEY_C):
        bank.keep(key, _media(tmp_path, f"{key[0]}.mp4", b"z" * 1000), {"duration": 1.0})
    old = time.time() - 3600
    for path in (tmp_path / "bank").rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    # Reading B makes it recent again, so A is the least recently used.
    assert bank.take(KEY_B, destination=lambda _facts: tmp_path / "b-again.mp4") is not None

    bank.enforce_budget()

    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "a-out.mp4") is None
    assert bank.take(KEY_B, destination=lambda _facts: tmp_path / "b-out.mp4") is not None


def test_this_runs_entries_survive_eviction_and_the_overflow_is_reported(tmp_path):
    bank = _bank(tmp_path, max_bytes=1500)
    bank.begin_run()
    bank.keep(KEY_A, _media(tmp_path, "a.mp4", b"z" * 1000), {"duration": 1.0})
    bank.keep(KEY_B, _media(tmp_path, "b.mp4", b"z" * 1000), {"duration": 1.0})

    eviction = bank.enforce_budget()

    assert eviction.overflowed
    assert bank.take(KEY_A, destination=lambda _facts: tmp_path / "a-out.mp4") is not None
    assert bank.take(KEY_B, destination=lambda _facts: tmp_path / "b-out.mp4") is not None


def test_two_writers_of_one_entry_leave_one_verified_entry(tmp_path):
    bank = _bank(tmp_path)
    payloads = {name: name.encode() * 50_000 for name in ("first", "second")}
    sources = {name: _media(tmp_path / name, "clip.mp4", data) for name, data in payloads.items()}
    start = threading.Barrier(2)

    def write(name: str) -> None:
        start.wait()
        for _ in range(20):
            bank.keep(KEY_A, sources[name], {"duration": float(len(name))})

    threads = [threading.Thread(target=write, args=(name,)) for name in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    taken = bank.take(KEY_A, destination=lambda _facts: tmp_path / "out.mp4")
    assert taken is not None
    data = taken.path.read_bytes()
    # Whichever writer won, the facts handed out belong to the bytes handed out.
    winner = next(name for name, payload in payloads.items() if payload == data)
    assert taken.facts == {"duration": float(len(winner))}


def test_a_reader_racing_a_writer_only_ever_sees_a_matching_pair(tmp_path):
    bank = _bank(tmp_path)
    payloads = {name: name.encode() * 50_000 for name in ("first", "second")}
    sources = {name: _media(tmp_path / name, "clip.mp4", data) for name, data in payloads.items()}
    bank.keep(KEY_A, sources["first"], {"duration": 5.0})
    stop = threading.Event()

    def write() -> None:
        while not stop.is_set():
            for name in payloads:
                bank.keep(KEY_A, sources[name], {"duration": float(len(name))})

    writer = threading.Thread(target=write)
    writer.start()
    try:
        for attempt in range(40):
            taken = bank.take(KEY_A, destination=lambda _facts, n=attempt: tmp_path / f"r{n}.mp4")
            if taken is None:
                continue
            data = taken.path.read_bytes()
            name = next(name for name, payload in payloads.items() if payload == data)
            assert taken.facts == {"duration": float(len(name))}
    finally:
        stop.set()
        writer.join()


def test_abandoned_partial_writes_are_swept(tmp_path):
    bank = _bank(tmp_path)
    bank.keep(KEY_A, _media(tmp_path, "a.mp4", b"bytes"), {"duration": 1.0})
    shard = next((tmp_path / "bank").rglob("*.json")).parent
    stale = shard / f".{KEY_B}.leftover.tmp"
    stale.write_bytes(b"half")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = shard / f".{KEY_C}.inflight.tmp"
    fresh.write_bytes(b"half")

    PreparedSourceBank(tmp_path / "bank", max_bytes=10_000_000).begin_run()

    assert not stale.exists()
    assert fresh.exists()
