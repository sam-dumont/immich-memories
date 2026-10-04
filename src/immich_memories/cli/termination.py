"""Turn SIGTERM into KeyboardInterrupt, so a cancelled command unwinds instead of vanishing."""

from __future__ import annotations

import signal
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def stop_on_sigterm() -> Iterator[None]:
    """Within the block SIGTERM raises KeyboardInterrupt, the way Ctrl+C already does.

    The web client cancels a render by signalling its process group; left to the default the
    process dies with its run row `running` and its scratch folders on disk.
    """

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
