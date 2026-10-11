"""A duck-typed picture for planner tests that build their pool by hand."""

from __future__ import annotations

from types import SimpleNamespace


class PictureFake(SimpleNamespace):
    """An Asset stand-in whose own clock is its UTC instant, as for a picture Immich gave
    no local clock. Reassigning `file_created_at` moves the clock with it."""

    @property
    def local_taken_at(self):
        return self.file_created_at
