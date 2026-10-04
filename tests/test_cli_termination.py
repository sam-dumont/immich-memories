"""A cancel from the web client is SIGTERM to the render's process group."""

import os
import signal

import pytest

from immich_memories.cli.termination import stop_on_sigterm


def test_sigterm_stops_the_render_as_an_interrupt_so_its_cleanup_runs():
    before = signal.getsignal(signal.SIGTERM)

    with pytest.raises(KeyboardInterrupt), stop_on_sigterm():
        os.kill(os.getpid(), signal.SIGTERM)

    assert signal.getsignal(signal.SIGTERM) is before
