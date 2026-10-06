"""Preflight reports the Laya audience check wherever the tier turns it on (#2148)."""

from __future__ import annotations

import io
import sys
import tarfile

from immich_memories.config import Config
from immich_memories.preflight import CheckStatus, run_preflight_checks
from immich_memories.preflight_laya import check_laya


def _mlx_archive(tmp_path):
    archive = tmp_path / "laya.tar"
    with tarfile.open(archive, "w") as bundle:
        info = tarfile.TarInfo("model.safetensors")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    return archive


def test_a_tier_without_laya_skips_the_check():
    assert check_laya(Config(tier="basic")).status is CheckStatus.SKIPPED


def test_a_missing_checkpoint_is_a_warning_naming_models_fetch(tmp_path):
    config = Config(tier="gpu", editorial={"laya_checkpoint": str(tmp_path / "absent.tar")})

    result = check_laya(config)

    assert result.status is CheckStatus.WARNING
    assert "models fetch" in (result.details or "")


def test_a_missing_laya_runtime_is_a_warning_naming_the_install(monkeypatch, tmp_path):
    # WHY: stands in for an install without laya-mlx (a fresh `make dev`).
    monkeypatch.setitem(sys.modules, "laya_mlx", None)
    config = Config(tier="gpu", editorial={"laya_checkpoint": str(_mlx_archive(tmp_path))})

    result = check_laya(config)

    assert result.status is CheckStatus.WARNING
    assert "laya-mlx" in (result.details or "")


def test_preflight_runs_the_laya_check(monkeypatch, tmp_path):
    # WHY: stands in for an install without laya-mlx (a fresh `make dev`).
    monkeypatch.setitem(sys.modules, "laya_mlx", None)
    config = Config(tier="gpu", editorial={"laya_checkpoint": str(_mlx_archive(tmp_path))})

    laya = [result for result in run_preflight_checks(config) if result.name == "Laya"]

    assert [result.status for result in laya] == [CheckStatus.WARNING]
