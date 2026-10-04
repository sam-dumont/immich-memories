"""Missing local music points at a step the reader can actually take."""

from __future__ import annotations

import sys

from immich_memories.config_loader import Config
from immich_memories.local_capabilities import local_capabilities


def _music_row(monkeypatch, prefix):
    # WHY: where this interpreter lives and whether ACE-Step is on disk are the install's
    # state; the test asks for an install that has no music and sits at `prefix`.
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: None
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_runtime.is_ace_step_importable", lambda: False
    )
    config = Config(ace_step={"enabled": True, "mode": "lib"})
    return next(row for row in local_capabilities(config) if row.name == "Local music")


def test_a_source_checkout_is_told_to_run_the_make_target(monkeypatch, tmp_path) -> None:
    (tmp_path / "Makefile").write_text("install-acestep:\n\techo\n")

    row = _music_row(monkeypatch, tmp_path / ".venv")

    assert row.status == "missing"
    assert "make install-acestep" in row.message


def test_a_container_or_pip_install_is_pointed_at_the_music_page(monkeypatch, tmp_path) -> None:
    row = _music_row(monkeypatch, tmp_path / "venv")

    assert row.status == "missing"
    assert "make install-acestep" not in row.message
    assert "docs/better/music" in row.message
