"""A worker's film a few percent off its planned length is the same film (#2780).

A ten-minute film of 150 clips came back at 589.1 s against the 604.0 s the preview
planned, and the whole run failed after its render. Frame rounding of every clip, card
and fade adds up on a long cut; only a real gap (a lost card or shot run) fails it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.generate import GenerationError
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.remote_render import check_film_length, film_length_bounds


def _clips(count: int) -> list[AssemblyClip]:
    return [AssemblyClip(Path(), 4.0, asset_id=f"clip-{index}") for index in range(count)]


def test_a_film_within_frame_rounding_of_the_plan_passes_quietly():
    assert check_film_length(603.0, 604.0, _clips(150)) is None


def test_a_film_a_few_percent_short_passes_with_a_warning_naming_both_lengths():
    warning = check_film_length(589.133, 603.984, _clips(150))

    assert warning is not None
    assert "589.1" in warning
    assert "604.0" in warning


def test_a_film_a_few_percent_long_passes_with_a_warning():
    warning = check_film_length(618.0, 603.984, _clips(150))

    assert warning is not None
    assert "618.0" in warning


def test_a_film_far_off_its_plan_fails_and_says_both_lengths():
    with pytest.raises(GenerationError, match=r"540\.0.*604\.0"):
        check_film_length(540.0, 603.984, _clips(150))


def test_a_short_film_keeps_its_frame_rounding_floor():
    """A 3% margin on a 10 s film is a third of a second: rounding still gets its frame each."""
    assert check_film_length(9.7, 10.0, _clips(12)) is None
    with pytest.raises(GenerationError):
        check_film_length(8.0, 10.0, _clips(12))


def test_music_made_for_the_longest_film_covers_every_film_accepted():
    """The early music take is made for the longest film the check lets through."""
    shortest, longest = film_length_bounds(603.984, _clips(150))

    assert check_film_length(longest, 603.984, _clips(150)) is not None
    assert check_film_length(shortest, 603.984, _clips(150)) is not None
    with pytest.raises(GenerationError):
        check_film_length(longest + 0.1, 603.984, _clips(150))


def _received(seconds: float, monkeypatch):
    """Check a returned 150-clip film whose preview planned 603.984 s."""
    from types import SimpleNamespace

    from immich_memories.processing import remote_render
    from immich_memories.processing.encoding_plan import OutputCodec
    from immich_memories.processing.output_canvas import resolve_output_canvas

    clips = _clips(150)
    # WHY: the preview needs a whole frozen run; the plan's length is the input here.
    monkeypatch.setattr(remote_render, "_expected_duration", lambda *_: 603.984)
    monkeypatch.setattr(remote_render, "_map_extra", lambda *_: 0.0)
    output = {"resolution": "1080p", "orientation": "portrait", "codec": "h265", "hdr_mode": "auto"}
    canvas = resolve_output_canvas(
        resolution="1080p", orientation="portrait", configured_resolution=(1920, 1080), clips=[]
    )
    request = {
        "plan": {"clips": [{"asset_id": c.asset_id, "start": 0.0, "end": 4.0} for c in clips]},
        "output": output | {"codec_policy": "strict"},
    }
    probe = SimpleNamespace(width=canvas.width, height=canvas.height, duration_seconds=seconds)
    plan = SimpleNamespace(container="mp4", codec=OutputCodec.H265, codec_substituted_from=None)
    params = SimpleNamespace(target_duration_seconds=None, timeline_plan=None)
    status = {"music_mute_windows": [(10.0, 12.0)]}
    return remote_render._validate_result(params, request, status, clips, probe, plan)


def test_the_received_film_a_few_percent_short_is_kept_with_its_warning(monkeypatch, caplog):
    warning = _received(589.133, monkeypatch)

    assert warning is not None and "589.1" in warning and "604.0" in warning
    assert warning in caplog.text


def test_the_received_film_far_off_its_plan_is_refused(monkeypatch):
    with pytest.raises(GenerationError, match=r"500\.0.*604\.0"):
        _received(500.0, monkeypatch)
