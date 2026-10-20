"""The hook runs the unit tests in CI's environment: packages CI's unit job lacks are hidden.

#2742: a test gated on an optional heavy package ran in the hook (the Mac
worktree has torch) and skipped in CI, so the hook's diff coverage passed where CI's failed.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

from tests import ci_parity

REPO = Path(__file__).resolve().parents[1]


def _dists(**requires: list[str]) -> dict[str, list[str]]:
    return requires


def test_blocked_modules_are_the_installed_ones_outside_the_ci_closure() -> None:
    owners = {"torch": ["torch"], "pytest": ["pytest"], "demucs": ["demucs"], "app": ["app"]}
    requires = _dists(
        app=["pytest; extra == 'dev'", "demucs; extra == 'demucs'"],
        pytest=[],
        demucs=["torch"],
        torch=[],
    )
    blocked = ci_parity.blocked_modules(
        roots=("app",), extras=("dev",), owners=owners, requires=requires
    )
    assert blocked == {"torch", "demucs"}


def test_a_package_pulled_in_by_a_ci_package_stays_visible() -> None:
    owners = {"numpy": ["numpy"], "app": ["app"]}
    requires = _dists(app=["numpy"], numpy=[])
    assert ci_parity.blocked_modules(("app",), ("dev",), owners, requires) == set()


def test_a_namespace_shared_with_a_ci_package_stays_visible() -> None:
    owners = {"google": ["protobuf", "google-cloud-x"], "app": ["app"]}
    requires = _dists(app=["protobuf"], protobuf=[], **{"google-cloud-x": []})
    assert ci_parity.blocked_modules(("app",), ("dev",), owners, requires) == set()


def test_the_extras_match_what_ci_installs_for_the_unit_job() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\ndev-test:\n", 1)[1].split("\n\n", 1)[0]
    sync_line = next(line for line in recipe.splitlines() if "uv sync" in line)
    assert tuple(re.findall(r"--extra (\S+)", sync_line)) == ci_parity.CI_UNIT_EXTRAS
    workflow = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    test_job = workflow.split("\n  test:\n", 1)[1].split("\n  integration-coverage:", 1)[0]
    assert "- run: make dev-test" in test_job


def test_hiding_a_package_makes_importorskip_skip_and_find_spec_miss(tmp_path: Path) -> None:
    (tmp_path / "fake_heavy_pkg.py").write_text("VALUE = 1\n", encoding="utf-8")
    code = textwrap.dedent(
        """
        import importlib.util, sys
        sys.path.insert(0, sys.argv[1])
        import fake_heavy_pkg  # importable before
        del sys.modules["fake_heavy_pkg"]
        from tests import ci_parity
        ci_parity.hide({"fake_heavy_pkg"})
        assert importlib.util.find_spec("fake_heavy_pkg") is None
        try:
            import fake_heavy_pkg
        except ModuleNotFoundError:
            print("hidden")
        else:
            raise SystemExit("still importable")
        """
    )
    done = subprocess.run(  # noqa: S603 - fixed interpreter and inline code
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.strip() == "hidden", done.stderr


def test_a_test_that_needs_a_hidden_package_skips_under_the_hook(tmp_path: Path) -> None:
    (tmp_path / "fake_heavy_pkg.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tmp_path / "test_needs_heavy.py"
    test_file.write_text(
        "import pytest\n"
        "def test_it():\n"
        "    pytest.importorskip('fake_heavy_pkg')\n"
        "    raise AssertionError('ran')\n",
        encoding="utf-8",
    )
    conftest = tmp_path / "conftest.py"
    conftest.write_text(
        f"import sys\nsys.path[:0] = [{str(REPO)!r}, {str(tmp_path)!r}]\n"
        "from tests import ci_parity\nci_parity.hide({'fake_heavy_pkg'})\n",
        encoding="utf-8",
    )
    done = subprocess.run(  # noqa: S603 - fixed interpreter and pytest arguments
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rs", "-q", str(test_file)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "1 skipped" in done.stdout, done.stdout


def test_the_real_environment_keeps_what_the_dev_extra_needs() -> None:
    blocked = ci_parity.blocked_modules_for_environment()
    assert not {"pytest", "immich_memories", "coverage", "xdist"} & blocked
