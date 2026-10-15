"""The warnings a config load gives reach the Settings page, not only the server log."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from immich_memories.config_warnings import config_warnings

_CONFIG = """\
immich:
  url: https://photos.example.com
output:
  not_a_key: 1
audio:
  pixabay_api_key: removed-long-ago
advanced:
  analysis:
    optimal_clip_duration: 5
  llm:
    base_url: http://reader.example.lan:8000/v1
    model: some-served-model
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(_CONFIG)
    return path


def test_every_kind_of_config_warning_is_collected(config_file: Path):
    warnings = config_warnings(config_file)

    text = "\n".join(warnings)
    assert "Ignoring unknown config key file: output.not_a_key" in text
    assert "audio.pixabay_api_key" in text
    assert "analysis.optimal_clip_duration is no longer supported" in text
    assert "advanced.llm.enabled is false" in text
    # Keys are named, values never are.
    assert "removed-long-ago" not in text
    assert "some-served-model" not in text


def test_a_second_read_still_names_what_the_first_load_already_logged(
    config_file: Path, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING):
        first = config_warnings(config_file)
        second = config_warnings(config_file)

    assert first == second
    # Collected for the page instead of logged again on every visit.
    assert not [r for r in caplog.records if r.name.startswith("immich_memories.config")]


def test_a_clean_config_has_no_warnings(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("immich:\n  url: https://photos.example.com\n")

    assert config_warnings(path) == []


def test_config_loads_on_several_threads_each_read_their_own_file(tmp_path: Path):
    """The web server loads the config on several request threads at once (Settings asks for
    the settings and the warnings together). A load that read another's half-built layers came
    back without the file, and became the server's config without an Immich URL."""
    from concurrent.futures import ThreadPoolExecutor

    from immich_memories.config_loader import Config

    paths = []
    for index in range(4):
        path = tmp_path / f"config-{index}.yaml"
        path.write_text(f"immich:\n  url: https://photos-{index}.example.com\n")
        paths.append(path)

    def load(index: int) -> str:
        return Config.from_yaml(paths[index % 4]).immich.url

    with ThreadPoolExecutor(max_workers=8) as pool:
        urls = list(pool.map(load, range(200)))

    assert urls == [f"https://photos-{index % 4}.example.com" for index in range(200)]


def test_a_bare_dollar_in_a_key_is_named_by_its_field_never_echoed(tmp_path: Path, monkeypatch):
    """The old bare `$NAME` form still gets its warning, without a piece of the secret."""
    monkeypatch.setenv("IMM_TEST_BARE_NAME", "set")
    path = tmp_path / "config.yaml"
    path.write_text(
        "immich:\n  url: https://photos.example.com\n  api_key: k3y$IMM_TEST_BARE_NAME\n"
    )

    text = "\n".join(config_warnings(path))

    assert "immich.api_key" in text
    assert "IMM_TEST_BARE_NAME" not in text
    assert "k3y" not in text
