"""Stand-in modules for a test's span, without disturbing the rest of `sys.modules`."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import pytest


@contextmanager
def swapped_modules(modules: Mapping[str, ModuleType | Any | None]) -> Iterator[None]:
    """Put these entries in `sys.modules`, then put back exactly those entries.

    `patch.dict(sys.modules, ...)` restores the whole dictionary instead, so it also drops
    every module first imported while it was active. The next import of such a module builds
    a second copy, and a later test then patches one copy while the code under test runs the
    other, or a native extension such as onnxruntime refuses to load twice. Which tests break
    depends on which ran first.
    """
    with pytest.MonkeyPatch.context() as patcher:
        for name, module in modules.items():
            patcher.setitem(sys.modules, name, module)
        yield
