"""An integration run keeps the environment it was launched with (#1540).

The real-Immich gate points HOME at a seeded home and reads its config at import time;
the unit suite's sealed home must never replace it.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.conftest import _TEST_ROOT


def test_an_integration_run_keeps_the_home_it_was_launched_with():
    assert _TEST_ROOT is not None
    assert not Path.home().resolve().is_relative_to(_TEST_ROOT.resolve())
    assert os.environ.get("IMMICH_URL") == "http://127.0.0.1:9/launched"
