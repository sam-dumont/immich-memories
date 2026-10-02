"""`${VAR}` expands in config.yaml only; saved settings and the environment are literal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from immich_memories.config_loader import Config

EXPANDED_URL = "https://expanded.example"
EXPANDED_VALUE = "expanded-value-0123456789abcdef0123456789"

# Every field that takes a `${VAR}` reference in config.yaml, with a value it accepts.
REFERENCE_FIELDS = [
    ("immich.url", EXPANDED_URL),
    ("immich.api_key", EXPANDED_VALUE),
    ("immich.accounts.family.url", EXPANDED_URL),
    ("immich.accounts.family.api_key", EXPANDED_VALUE),
    ("database.url", "sqlite:///expanded.db"),
    ("auth.password", EXPANDED_VALUE),
    ("auth.client_secret", EXPANDED_VALUE),
    ("auth.issuer_url", EXPANDED_URL),
    ("auth.client_id", EXPANDED_VALUE),
    ("render.worker_base_url", EXPANDED_URL),
    ("render.worker_token", EXPANDED_VALUE),
    ("llm.api_key", EXPANDED_VALUE),
    ("musicgen.base_url", EXPANDED_URL),
    ("musicgen.api_key", EXPANDED_VALUE),
    ("ace_step.api_url", EXPANDED_URL),
    ("ace_step.api_key", EXPANDED_VALUE),
    ("editorial.annotation_database", "/expanded/annotations.sqlite"),
    ("editorial.laya_checkpoint", "/expanded/laya.onnx"),
    ("editorial.preparation.head_bundle", "/expanded/heads"),
    ("editorial.preparation.detector_python", "/expanded/python"),
    ("editorial.preparation.detector_cache_dir", "/expanded/cache"),
    ("editorial.preparation.marqo_onnx", "/expanded/marqo.onnx"),
    ("editorial.preparation.caption_api_key", EXPANDED_VALUE),
]

# Fields with no format check, so a literal `${VAR}` is a value they hold as written.
LITERAL_FIELDS = [
    "immich.url",
    "immich.api_key",
    "auth.password",
    "auth.client_id",
    "render.worker_token",
    "llm.api_key",
    "musicgen.api_key",
    "ace_step.api_key",
]


def _value(config: Config, key: str) -> Any:
    value: Any = config
    for part in key.split("."):
        value = value[part] if isinstance(value, dict) else getattr(value, part)
    return value


def _yaml_for(key: str, value: str) -> str:
    *parents, leaf = key.split(".")
    lines = [f"{'  ' * depth}{part}:" for depth, part in enumerate(parents)]
    lines.append(f"{'  ' * len(parents)}{leaf}: {value}")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(("key", "expected"), REFERENCE_FIELDS)
def test_a_reference_in_config_yaml_expands(
    key: str, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: the harness pins model paths in the environment, which wins over YAML.
    monkeypatch.delenv(f"IMMICH_MEMORIES_{key.upper().replace('.', '__')}", raising=False)
    monkeypatch.setenv("FILE_REFERENCE", expected)
    source = tmp_path / "config.yaml"
    source.write_text(_yaml_for(key, '"${FILE_REFERENCE}"'))

    config = Config.from_yaml(source, stored={})

    assert _value(config, key) == expected


@pytest.mark.parametrize("key", LITERAL_FIELDS)
def test_a_stored_value_is_never_expanded(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a row written past `save_settings` stays the text that was saved."""
    monkeypatch.setenv("STORED_REFERENCE", EXPANDED_VALUE)
    source = tmp_path / "config.yaml"
    source.write_text("")

    config = Config.from_yaml(source, stored={key: "${STORED_REFERENCE}"})

    assert _value(config, key) == "${STORED_REFERENCE}"


def test_a_stored_caption_key_reference_is_no_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A literal `${VAR}` is never sent as a bearer key, and never expanded either."""
    monkeypatch.setenv("STORED_REFERENCE", EXPANDED_VALUE)
    source = tmp_path / "config.yaml"
    source.write_text("")

    config = Config.from_yaml(
        source, stored={"editorial.preparation.caption_api_key": "${STORED_REFERENCE}"}
    )

    assert config.editorial.preparation.caption_api_key == ""


def test_an_environment_value_is_never_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IMMICH_API_KEY", raising=False)
    monkeypatch.setenv("OTHER_SECRET", EXPANDED_VALUE)
    monkeypatch.setenv("IMMICH_MEMORIES_IMMICH__API_KEY", "${OTHER_SECRET}")
    source = tmp_path / "config.yaml"
    source.write_text("")

    config = Config.from_yaml(source, stored={})

    assert config.immich.api_key == "${OTHER_SECRET}"


def test_the_file_wins_over_a_stored_value_and_only_the_file_expands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FILE_REFERENCE", "from-the-file")
    source = tmp_path / "config.yaml"
    source.write_text('llm:\n  api_key: "${FILE_REFERENCE}"\n')

    config = Config.from_yaml(source, stored={"llm.model": "${FILE_REFERENCE}"})

    assert config.llm.api_key == "from-the-file"
    assert config.llm.model == "${FILE_REFERENCE}"
