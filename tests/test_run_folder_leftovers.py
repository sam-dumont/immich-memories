"""A finished film folder holds the film, not the mastered music behind it (#2031)."""

from __future__ import annotations

from types import SimpleNamespace

from immich_memories.generate import _clear_run_intermediates


def _params(*, keep: bool = False):
    return SimpleNamespace(debug_preserve_intermediates=keep)


def test_mastered_wav_is_removed_next_to_the_film(tmp_path):
    (tmp_path / "film.mp4").write_bytes(b"film")
    (tmp_path / "mastered_tender_acoustic.wav").write_bytes(b"wav")

    _clear_run_intermediates(_params(), [], tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["film.mp4"]


def test_mastered_wav_stays_when_intermediates_are_kept(tmp_path):
    (tmp_path / "mastered_tender_acoustic.wav").write_bytes(b"wav")

    _clear_run_intermediates(_params(keep=True), [], tmp_path)

    assert (tmp_path / "mastered_tender_acoustic.wav").exists()


def test_empty_folder_of_a_stopped_render_is_removed(tmp_path):
    folder = tmp_path / "cancelled_run"
    folder.mkdir()

    _clear_run_intermediates(_params(), [], folder)

    assert not folder.exists()
