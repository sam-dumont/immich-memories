"""Immich Memories - Create yearly video compilations from your Immich photo library."""

import os

# HF builds headers even for local cache reads; its agent registry must never contact the Hub.
# Set this before optional imports cache the flag, without blocking explicit model downloads.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

__author__ = "Immich Memories Contributors"

# WHY first: a run's `startup` span measures from here, so it must precede the config imports.
from immich_memories import process_start  # noqa: F401, I001

from immich_memories._version import __version__
from immich_memories.config import Config, get_config

__all__ = ["Config", "get_config", "__version__"]
