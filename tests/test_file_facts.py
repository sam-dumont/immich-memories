"""Facts about a large file are worked out once per version of the file, not once per process."""

import hashlib
import os
import stat

import pytest

from immich_memories import local_inference
from immich_memories.audio import track_tempo
from immich_memories.cache import file_facts


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A throwaway home: the facts file lives under it, never under the real one."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _counted(calls):
    def compute(path):
        calls.append(path)
        return f"fact-of-{path.read_bytes().decode()}"

    return compute


def test_a_fact_is_worked_out_once_and_read_back_by_the_next_process(home, tmp_path):
    target = tmp_path / "weights.bin"
    target.write_bytes(b"one")
    calls = []

    first = file_facts.remembered_fact("weights", target, _counted(calls))
    second = file_facts.remembered_fact("weights", target, _counted(calls))

    assert first == second == "fact-of-one"
    assert len(calls) == 1
    store = home / ".immich-memories" / "cache" / "file-facts" / "weights.json"
    assert stat.S_IMODE(store.stat().st_mode) == 0o600


def test_a_file_that_changed_is_worked_out_again(home, tmp_path):
    target = tmp_path / "weights.bin"
    target.write_bytes(b"one")
    calls = []
    file_facts.remembered_fact("weights", target, _counted(calls))

    target.write_bytes(b"two!")
    later = os.stat(target).st_mtime_ns + 1_000_000_000
    os.utime(target, ns=(later, later))

    assert file_facts.remembered_fact("weights", target, _counted(calls)) == "fact-of-two!"
    assert len(calls) == 2


def test_no_answer_is_never_remembered(home, tmp_path):
    target = tmp_path / "track.wav"
    target.write_bytes(b"silence")
    calls = []

    def nothing(path):
        calls.append(path)

    assert file_facts.remembered_fact("tempo", target, nothing) is None
    assert file_facts.remembered_fact("tempo", target, nothing) is None
    assert len(calls) == 2


def test_an_unwritable_home_still_answers(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the home directory should be")
    monkeypatch.setenv("HOME", str(blocked))
    target = tmp_path / "weights.bin"
    target.write_bytes(b"one")

    assert file_facts.remembered_fact("weights", target, _counted([])) == "fact-of-one"


def test_the_local_reader_weights_are_hashed_once_across_processes(home, tmp_path, monkeypatch):
    """A 5 GB GGUF was read end to end at the start of every process that asked who it was."""
    weights = tmp_path / "reader.gguf"
    weights.write_bytes(b"gguf weights")
    hashed = []
    real = hashlib.file_digest

    def counting(stream, digest):
        hashed.append(digest)
        return real(stream, digest)

    # WHY: counts reads of the weights; the digest is still the real one.
    monkeypatch.setattr(local_inference.hashlib, "file_digest", counting)
    signature = (weights.stat().st_size, weights.stat().st_mtime_ns, weights.stat().st_ctime_ns)

    first = local_inference._weight_digest(weights, signature)
    local_inference._weight_digest.cache_clear()  # a new process starts with nothing in memory
    second = local_inference._weight_digest(weights, signature)

    assert first == second == hashlib.sha256(b"gguf weights").hexdigest()
    assert len(hashed) == 1

    weights.write_bytes(b"other weights")
    local_inference._weight_digest.cache_clear()
    changed = weights.stat()
    third = local_inference._weight_digest(
        weights, (changed.st_size, changed.st_mtime_ns, changed.st_ctime_ns)
    )

    assert third == hashlib.sha256(b"other weights").hexdigest()
    assert len(hashed) == 2


def test_a_bundled_track_is_decoded_for_its_tempo_once_across_films(home, tmp_path, monkeypatch):
    tracks = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    for track in tracks:
        track.write_bytes(track.name.encode())
    decoded = []

    def measured(path):
        decoded.append(path.name)
        return 120.0 if path.name == "a.mp3" else 100.0

    # WHY: the ffmpeg decode is the boundary this counts; the cadence choice stays real.
    monkeypatch.setattr(track_tempo, "detect_bpm", measured)

    first_film = track_tempo.track_for_cadence(tracks, cadence_seconds=4.0)
    second_film = track_tempo.track_for_cadence(tracks, cadence_seconds=4.0)

    assert first_film == second_film == tracks[0]
    assert sorted(decoded) == ["a.mp3", "b.mp3"]


def test_a_missing_file_is_asked_about_every_time(home, tmp_path):
    calls = []

    def absent(path):
        calls.append(path)

    assert file_facts.remembered_fact("tempo", tmp_path / "gone.wav", absent) is None
    assert len(calls) == 1
