"""Read legacy file locations without opening the store or selecting a compute tier."""

from pathlib import Path

from pydantic_settings import EnvSettingsSource

from immich_memories.config_loader import Config, _load_yaml_data
from immich_memories.config_models import CacheConfig, expand_file_references
from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.config_models_render import OutputConfig


def legacy_path_settings(home: Path) -> tuple[CacheConfig, EditorialConfig, OutputConfig]:
    """Resolve path sections from YAML and environment without constructing runtime Config."""
    loaded = expand_file_references(Config, _load_yaml_data(home / "config.yaml"))
    environment = EnvSettingsSource(Config)()
    cache = (loaded.get("cache") or {}) | (environment.get("cache") or {})
    editorial = (loaded.get("editorial") or {}) | (environment.get("editorial") or {})
    output = (loaded.get("output") or {}) | (environment.get("output") or {})
    return (
        CacheConfig.model_validate(cache),
        EditorialConfig.model_validate(
            {"annotation_database": editorial.get("annotation_database", "")}
        ),
        OutputConfig.model_validate({"directory": output.get("directory", "~/Videos/Memories")}),
    )
