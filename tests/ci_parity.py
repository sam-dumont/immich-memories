"""Make the hook's unit run see the packages CI's unit job installs, and no others.

CI's unit shards run `make dev-test` (`uv sync --extra dev`). A contributor's venv usually
holds more: `make dev` adds every runtime extra, `make install-acestep` adds torch and
demucs. A test that starts with `pytest.importorskip("torch")` ran there and skipped in CI,
so the hook's diff coverage passed where CI's failed (#2742).

With `HOOK_CI_PARITY=1` (set by `make hook-tests`) this module hides every installed
top-level module whose distributions are not reachable from the project's base dependencies
plus the extras CI's unit job syncs. `import` raises `ModuleNotFoundError`, so `importorskip`
skips and `importlib.util.find_spec` answers `None`, exactly as on a CI runner. The hidden
set is computed from the installed metadata, so a new extra or a new dependency cannot drift
out of it; `CI_UNIT_EXTRAS` is checked against the Makefile by tests/test_ci_parity.py.
"""

from __future__ import annotations

import importlib.abc
import importlib.metadata as metadata
import importlib.util
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ENV_FLAG = "HOOK_CI_PARITY"
PROJECT = "immich-memories"
# What `make dev-test` syncs for CI's unit shards.
CI_UNIT_EXTRAS = ("dev",)

REPO = Path(__file__).resolve().parents[1]

_hidden: frozenset[str] = frozenset()


def own_modules(repo: Path = REPO) -> set[str]:
    """Top-level modules that live in this repository (root and `src/`), whatever wheels claim.

    A third-party wheel can list our names in its `top_level.txt` (mlx lists `tests`), which
    would make the closure check hide the project's own packages.
    """
    found: set[str] = set()
    for base in (repo, repo / "src"):
        for entry in base.iterdir():
            if not entry.name.isidentifier():
                continue
            if entry.is_file() and entry.suffix == ".py":
                found.add(entry.stem)
            elif entry.is_dir() and ((entry / "__init__.py").exists() or any(entry.glob("*.py"))):
                found.add(entry.name)
    return found


def blocked_modules(
    roots: Sequence[str],
    extras: Sequence[str],
    owners: Mapping[str, Sequence[str]],
    requires: Mapping[str, Sequence[str]],
) -> set[str]:
    """Top-level modules installed here whose every owning distribution is outside CI's set.

    `owners` maps a top-level module to its distributions, `requires` a distribution to its
    requirement strings. A distribution is in CI's set when the roots (with `extras`) reach it.
    """
    wanted = {canonicalize_name(name) for name in roots}
    queue = [(canonicalize_name(name), tuple(extras)) for name in roots]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    normalized = {canonicalize_name(name): reqs for name, reqs in requires.items()}
    while queue:
        item = queue.pop()
        if item in seen:
            continue
        seen.add(item)
        name, active = item
        for text in normalized.get(name, ()):
            req = Requirement(text)
            if req.marker and not any(
                req.marker.evaluate({"extra": extra}) for extra in (*active, "")
            ):
                continue
            dep = canonicalize_name(req.name)
            wanted.add(dep)
            queue.append((dep, tuple(req.extras)))
    return {
        module
        for module, dists in owners.items()
        if not any(canonicalize_name(dist) in wanted for dist in dists)
    }


def blocked_modules_for_environment() -> set[str]:
    owners = metadata.packages_distributions()
    requires = {
        dist.metadata["Name"]: list(dist.requires or ())
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }
    return blocked_modules((PROJECT,), CI_UNIT_EXTRAS, owners, requires) - own_modules()


class _Hider(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001, ARG002
        if fullname.partition(".")[0] in _hidden:
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


def hide(modules: Iterable[str]) -> None:
    """Make these top-level modules look uninstalled."""
    global _hidden  # noqa: PLW0603 - one process-wide switch, like the import system itself
    _hidden = frozenset(modules)
    if not any(isinstance(finder, _Hider) for finder in sys.meta_path):
        sys.meta_path.insert(0, _Hider())
        real_find_spec = importlib.util.find_spec

        def find_spec(name: str, package: str | None = None):
            if name.partition(".")[0] in _hidden:
                return None
            return real_find_spec(name, package)

        importlib.util.find_spec = find_spec
    for loaded in [m for m in sys.modules if m.partition(".")[0] in _hidden]:
        del sys.modules[loaded]


def activate_from_env() -> None:
    if os.environ.get(ENV_FLAG) == "1":
        hide(blocked_modules_for_environment())
