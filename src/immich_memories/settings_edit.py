"""Saving settings: the one write path for the UI and the CLI, and the explicit move out of config.yaml.

A save writes the database only. It refuses a key that env or config.yaml overrides
(the save would do nothing) and names what overrides it, refuses bootstrap keys, and
refuses a secret while `IMMICH_MEMORIES_SECRET_KEY` is unset. Every value is checked
against the config schema, and the whole config is rebuilt with it, before anything
is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from immich_memories.config_loader import (
    _TIER2_SECTIONS,
    Config,
    _load_yaml_data,
    get_config,
    get_config_path,
)
from immich_memories.config_sources import SettingSource, describe_settings
from immich_memories.security import write_secret_file
from immich_memories.settings_store import (
    SECRET_KEY_ENV,
    SecretKeyError,
    is_bootstrap_key,
    is_secret_key,
    secret_key_from_env,
    settings_store,
)


class SettingRefused(ValueError):
    """A save or move that would not take effect, or would store something unsafe."""


def _field_type(key: str) -> Any:
    model: type[BaseModel] = Config
    *parents, leaf = key.split(".")
    for part in parents:
        field = _field(model, part, key)
        nested = next(
            (
                arg
                for arg in (field.annotation, *getattr(field.annotation, "__args__", ()))
                if _is_model(arg)
            ),
            None,
        )
        if nested is None:
            raise SettingRefused(f"unknown setting {key}")
        model = nested
    field = _field(model, leaf, key)
    return Annotated[field.annotation, *field.metadata] if field.metadata else field.annotation


def _is_model(candidate: Any) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, BaseModel)


def _field(model: type[BaseModel], name: str, key: str) -> Any:
    for field_name, field in model.model_fields.items():
        if name in (field_name, field.alias):
            return field
    raise SettingRefused(f"unknown setting {key}")


def _checked(key: str, value: Any) -> Any:
    try:
        adapter: TypeAdapter[Any] = TypeAdapter(_field_type(key))
        validated = adapter.validate_python(value)
    except ValidationError as error:
        problem = error.errors()[0]["msg"]
        raise SettingRefused(f"{key}: {problem}") from None
    return adapter.dump_python(validated, mode="json")


def _refusal(entry: SettingSource) -> str | None:
    if is_bootstrap_key(entry.key):
        return f"{entry.key} is read before the database opens; set it in the environment or config.yaml"
    if entry.source == "env":
        return f"{entry.key} is set by the environment variable {entry.override}; change it there"
    if entry.source == "file":
        return (
            f"{entry.key} is set in config.yaml as {entry.override}; edit the file, or run "
            f"`immich-memories config move-to-db {entry.key}`"
        )
    return None


def _config_with(path: Path, stored: dict[str, Any]) -> Config:
    try:
        return Config.from_yaml(path, stored=stored)
    except ValidationError as error:
        problem = error.errors()[0]
        where = ".".join(str(part) for part in problem["loc"])
        raise SettingRefused(f"{where}: {problem['msg']}") from None


def save_settings(changes: Mapping[str, Any], *, path: Path | None = None) -> Config:
    """Save settings to the database and return the reloaded config.

    Keys are runtime paths (`llm.model`, not `advanced.llm.model`). Nothing is written
    when any key is refused; `SettingRefused` names the key and why. config.yaml and the
    environment are never touched.
    """
    path = path or get_config_path()
    config = get_config()
    report = {entry.key: entry for entry in describe_settings(config, path=path)}
    checked: dict[str, Any] = {}
    for key, value in changes.items():
        entry = report.get(key)
        if entry is None:
            raise SettingRefused(f"unknown setting {key}")
        if refusal := _refusal(entry):
            raise SettingRefused(refusal)
        if is_secret_key(key) and not secret_key_from_env():
            raise SettingRefused(
                f"{key} is a secret and {SECRET_KEY_ENV} is not set, so it cannot be stored in "
                "the database. Set the key, or set this value in the environment or config.yaml."
            )
        checked[key] = _checked(key, value)
    if not checked:
        return config
    _write(config, path, checked)
    return get_config(reload=True)


def _write(config: Config, path: Path, checked: dict[str, Any]) -> None:
    store = settings_store(config, create=True)
    assert store is not None  # create=True always opens one
    _config_with(path, {**store.values(), **checked})
    try:
        store.save(checked)
    except SecretKeyError as error:
        raise SettingRefused(str(error)) from None


def _remove_from_file(raw: dict, key: str) -> None:
    parts = key.split(".")
    _pop_path(raw, parts)
    advanced = raw.get("advanced")
    if parts[0] in _TIER2_SECTIONS and isinstance(advanced, dict):
        _pop_path(advanced, parts)
        if not advanced:
            del raw["advanced"]


def _pop_path(data: dict, parts: list[str]) -> None:
    *parents, leaf = parts
    holders = [data]
    for part in parents:
        child = holders[-1].get(part)
        if not isinstance(child, dict):
            return
        holders.append(child)
    if leaf not in holders[-1]:
        return
    del holders[-1][leaf]
    # Drop the sections the move emptied, so the file does not keep `llm: {}` behind.
    for holder, part in zip(reversed(holders[:-1]), reversed(parents), strict=True):
        if holder[part] == {}:
            del holder[part]


def _file_value(key: str, loaded: dict) -> Any:
    value: Any = loaded
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise SettingRefused(f"{key} is not set in config.yaml")
        value = value[part]
    if "${" in str(value):
        raise SettingRefused(
            f"{key} reads an environment variable in config.yaml ({value}); keep it there, or "
            "save the value itself from the settings page"
        )
    return value


def move_to_database(keys: list[str], *, path: Path | None = None) -> Path:
    """Move keys out of config.yaml into the database, and return the backup of the old file.

    The explicit action behind `config move-to-db`: nothing moves on its own. Each value
    is saved to the database first, then its line is removed from config.yaml (from the
    top level or from `advanced:`, wherever it was written). The rest of the file keeps its
    values, `${VAR}` references included; comments are not kept, so the previous file is
    copied to `config.yaml.bak` first.
    """
    path = path or get_config_path()
    config = get_config()
    loaded = _load_yaml_data(path)
    values = {}
    for key in keys:
        if is_bootstrap_key(key):
            raise SettingRefused(
                f"{key} is read before the database opens, so it stays in config.yaml"
            )
        if is_secret_key(key) and not secret_key_from_env():
            raise SettingRefused(f"{key} is a secret and {SECRET_KEY_ENV} is not set; set it first")
        values[key] = _checked(key, _file_value(key, loaded))
    _write(config, path, values)

    original = path.read_text()
    raw = yaml.safe_load(original) or {}
    for key in keys:
        _remove_from_file(raw, key)
    backup = path.with_name(path.name + ".bak")
    write_secret_file(backup, original)
    write_secret_file(path, yaml.safe_dump(raw, default_flow_style=False, sort_keys=False))
    get_config(reload=True)
    return backup
