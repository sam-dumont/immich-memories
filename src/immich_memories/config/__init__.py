"""Configuration: the config models, how a config is loaded, and what loading it says.

The models live in `config.models`, one module per domain; `loader` builds `Config` from its
sources. This package re-exports the names most callers need, so
``from immich_memories.config import Config, get_config`` works from anywhere.
"""

from immich_memories.config.loader import (  # noqa: F401
    Config,
    get_config,
    get_config_path,
    init_config_dir,
    load_config,
    set_config,
)
from immich_memories.config.models.analysis import (  # noqa: F401
    AnalysisConfig,
)
from immich_memories.config.models.editorial import EditorialConfig  # noqa: F401
from immich_memories.config.models.llm import LLMConfig  # noqa: F401
from immich_memories.config.models.render import (  # noqa: F401
    DefaultsConfig,
    OutputConfig,
    PhotoConfig,
    TitleScreenConfig,
)
from immich_memories.config.models.resources import (  # noqa: F401
    CacheConfig,
    HardwareAccelConfig,
    ImmichConfig,
    expand_env_vars,
)
from immich_memories.config.models.server import ServerConfig
from immich_memories.config.models.soundtrack import (  # noqa: F401
    ACEStepConfig,
    AudioConfig,
    MusicGenConfig,
)

__all__ = [
    "ACEStepConfig",
    "AnalysisConfig",
    "AudioConfig",
    "CacheConfig",
    "Config",
    "DefaultsConfig",
    "EditorialConfig",
    "HardwareAccelConfig",
    "ImmichConfig",
    "LLMConfig",
    "MusicGenConfig",
    "OutputConfig",
    "PhotoConfig",
    "ServerConfig",
    "TitleScreenConfig",
    "expand_env_vars",
    "get_config",
    "get_config_path",
    "init_config_dir",
    "load_config",
    "set_config",
]
