"""Where every setting's effective value comes from: env, config.yaml, the database or the default.

The report behind the settings page and `config show`. It names the exact override
(`IMMICH_MEMORIES_LLM__MODEL`, `advanced.llm.model`) so a greyed-out setting says where
to change it. Secrets are masked; nothing here returns one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, TypeAdapter

from immich_memories.config_loader import (
    _TIER2_SECTIONS,
    Config,
    _load_yaml_data,
    env_alias_overrides,
    get_config,
    get_config_path,
)
from immich_memories.db import redact_url
from immich_memories.settings_store import is_bootstrap_key, is_secret_key, settings_store

Source = Literal["env", "file", "database", "default"]

MASK = "***"
_JSON: TypeAdapter[Any] = TypeAdapter(Any)


@dataclass(frozen=True)
class SettingSource:
    """One leaf setting: its effective value (secrets masked), where it comes from, and what overrides it.

    `override` is the environment variable or the config.yaml key path (as written in the
    file, `advanced.` included) that sets the value; None when the source is the database
    or the default.
    """

    key: str
    value: Any
    source: Source
    override: str | None
    secret: bool

    @property
    def editable(self) -> bool:
        """Whether a save from the UI or CLI would take effect."""
        return self.source in ("database", "default") and not is_bootstrap_key(self.key)


def leaf_values(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every leaf of a config model as (runtime key path, value); nested sections are walked."""
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        key = f"{prefix}{field.alias or name}"
        if isinstance(value, BaseModel):
            yield from leaf_values(value, f"{key}.")
        else:
            yield key, value


def _env_override(key: str, env_names: Mapping[str, str], aliases: Mapping[str, str]) -> str | None:
    parts = key.upper().split(".")
    # The most specific name wins the report; a whole-section variable covers its keys too.
    for depth in range(len(parts), 0, -1):
        name = "IMMICH_MEMORIES_" + "__".join(parts[:depth])
        if name in env_names:
            return env_names[name]
    if is_bootstrap_key(key):
        name = "IMMICH_MEMORIES_" + key.upper().replace(".", "_")
        if os.environ.get(name):
            return name
    return aliases.get(key)


def _holds(data: Any, parts: list[str]) -> bool:
    for part in parts:
        if not isinstance(data, dict) or part not in data:
            return False
        data = data[part]
    return True


def _file_override(key: str, loaded: dict, raw: dict) -> str | None:
    parts = key.split(".")
    if not _holds(loaded, parts):
        return None
    # The top level wins a tie when both placements are written, so it is the one to name.
    if parts[0] in _TIER2_SECTIONS and not _holds(raw, parts):
        return f"advanced.{key}"
    return key


def _raw_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _stored_keys(config: Config) -> set[str]:
    store = settings_store(config, create=False)
    return store.stored_keys() if store is not None else set()


def _display(key: str, value: Any, secret: bool) -> Any:
    if secret:
        return MASK if value else value
    if key == "database.url" and isinstance(value, str):
        return redact_url(value)
    return _JSON.dump_python(value, mode="json")


def describe_settings(
    config: Config | None = None,
    *,
    path: Path | None = None,
    stored_keys: set[str] | None = None,
) -> list[SettingSource]:
    """Every leaf setting with its effective value, source and exact override name.

    Precedence is env > config.yaml > database > default. Without arguments this
    describes the loaded config, its file, and the keys saved in its store.
    """
    config = config or get_config()
    path = path or get_config_path()
    loaded = _load_yaml_data(path)
    raw = _raw_yaml(path)
    env_names = {name.upper(): name for name, value in os.environ.items() if value}
    aliases = env_alias_overrides(config)
    stored = _stored_keys(config) if stored_keys is None else stored_keys

    report = []
    for key, value in leaf_values(config):
        secret = is_secret_key(key)
        source: Source = "default"
        override = _env_override(key, env_names, aliases)
        if override:
            source = "env"
        elif override := _file_override(key, loaded, raw):
            source = "file"
        elif key in stored:
            source = "database"
        report.append(SettingSource(key, _display(key, value, secret), source, override, secret))
    return report
