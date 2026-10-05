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


def _temp_segment(tmp_path):
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.security import private_temp_dir

    segment = private_temp_dir("clips") / f"clip_{tmp_path.name}_1.0_4.0.mp4"
    segment.write_bytes(b"segment")
    return segment, AssemblyClip(path=segment, duration=3.0, asset_id="video")


def test_kept_intermediates_bring_the_cut_segments_into_the_run_folder(tmp_path):
    """#2133: the extracted segments live in a private temp dir and were deleted even with
    --keep-intermediates, so a kept run had nothing of its cut to debug."""
    segment, clip = _temp_segment(tmp_path)
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    (run_folder / "film.mp4").write_bytes(b"film")

    _clear_run_intermediates(_params(keep=True), [clip], run_folder)

    kept = run_folder / ".intermediates" / segment.name
    assert kept.read_bytes() == b"segment"


def test_segments_are_removed_when_intermediates_are_not_kept(tmp_path):
    segment, clip = _temp_segment(tmp_path)
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    (run_folder / "film.mp4").write_bytes(b"film")

    _clear_run_intermediates(_params(), [clip], run_folder)

    assert not segment.exists()
    assert not (run_folder / ".intermediates").exists()
