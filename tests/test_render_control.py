"""A render can be told to stop, and its FFmpeg children end with it (#2687)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from immich_memories.processing.render_control import (
    RenderControl,
    RenderStopped,
    check_render_stopped,
    owned_child,
)


def test_a_stop_is_seen_at_the_next_seam_and_not_swallowed_by_fallbacks():
    control = RenderControl()
    with control:
        check_render_stopped()
        control.stop()
        with pytest.raises(RenderStopped):
            try:
                check_render_stopped()
            except Exception:  # noqa: BLE001  # a fallback that must not catch it
                pytest.fail("RenderStopped was caught as an ordinary error")


def test_nothing_stops_a_render_that_has_no_control():
    check_render_stopped()


def test_a_stop_ends_the_children_the_render_owns():
    control = RenderControl()
    # WHY: a real child process stands in for FFmpeg; only its lifetime matters.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with control, owned_child(child):
            control.stop()
            assert child.wait(timeout=15) != 0
    finally:
        child.kill()


def test_a_child_started_after_the_stop_is_ended_at_once():
    control = RenderControl()
    control.stop()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        with control, pytest.raises(RenderStopped), owned_child(child):
            pass
        assert child.poll() is not None
    finally:
        child.kill()
