"""A wheel ships the built web client or is not built at all (#1580).

The client is not committed: the release job and the Docker image build it first. A wheel
built without it would install a server whose every page says the client is missing, so the
build hook refuses it. An editable install (`uv sync`) is a source checkout and builds the
client with `make dev`, so it is never refused.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hatch_build.py"


@pytest.fixture
def hook(monkeypatch):
    interface = types.ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = object  # type: ignore[attr-defined]
    # WHY: hatchling lives only in the isolated build environment, not in the dev venv.
    monkeypatch.setitem(sys.modules, "hatchling.builders.hooks.plugin.interface", interface)
    spec = importlib.util.spec_from_file_location("hatch_build", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _built(root: Path) -> Path:
    client = root / "src" / "immich_memories" / "web" / "client"
    client.mkdir(parents=True)
    (client / "index.html").write_text("<div id=app></div>")
    return root


def test_a_wheel_without_the_client_is_refused_with_the_command_that_builds_it(hook, tmp_path):
    problem = hook.missing_client(tmp_path, "standard")

    assert problem is not None
    assert "make web-build" in problem


def test_a_wheel_with_the_client_builds(hook, tmp_path):
    assert hook.missing_client(_built(tmp_path), "standard") is None


def test_an_editable_install_never_needs_the_client(hook, tmp_path):
    assert hook.missing_client(tmp_path, "editable") is None


@pytest.fixture
def brand(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_web_brand", HOOK.parent / "scripts" / "check_web_brand.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SOURCE", tmp_path / "src")
    monkeypatch.setattr(module, "BUNDLE", tmp_path / "client")
    (tmp_path / "src").mkdir()
    return module


def test_the_logo_guard_refuses_to_pass_on_a_bundle_that_was_never_built(brand):
    assert brand.main(["--require-bundle"]) == 1


def test_the_logo_guard_passes_a_clean_built_bundle(brand, tmp_path):
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / "index.html").write_text("<div id=app></div>")

    assert brand.main(["--require-bundle"]) == 0
