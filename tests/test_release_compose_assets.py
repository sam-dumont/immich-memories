"""Release downloads use the same image version across tier and hardware files."""

from pathlib import Path

import pytest
from scripts.package_compose import package_compose_assets

ROOT = Path(__file__).resolve().parents[1]


def test_release_compose_assets_pin_the_candidate_and_exclude_private_files(tmp_path):
    outputs = package_compose_assets(ROOT, "1.2.3-rc.4", tmp_path)

    assert {path.name for path in outputs} == {
        "docker-compose.yml",
        "example.env",
        "docker-compose.gpu.yml",
        "docker-compose.full.yml",
        "docker-compose.cuda.yml",
        "docker-compose.gpu-worker.yml",
        "docker-compose.postgres.yml",
    }
    assert "IMMICH_MEMORIES_VERSION=1.2.3-rc.4" in (tmp_path / "example.env").read_text()
    for name in (
        "docker-compose.yml",
        "docker-compose.gpu.yml",
        "docker-compose.cuda.yml",
        "docker-compose.gpu-worker.yml",
    ):
        text = (tmp_path / name).read_text()
        assert "${IMMICH_MEMORIES_VERSION:-1.2.3-rc.4}" in text
        assert "${IMMICH_MEMORIES_VERSION:-latest}" not in text


@pytest.mark.parametrize("version", ["latest", "v1.2.3", "1.2.3rc4"])
def test_compose_release_assets_require_a_release_identity(tmp_path, version):
    with pytest.raises(ValueError, match="release version"):
        package_compose_assets(ROOT, version, tmp_path)
