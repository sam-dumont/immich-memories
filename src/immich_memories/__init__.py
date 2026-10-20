"""Immich Memories - Create yearly video compilations from your Immich photo library."""

import os

# HF builds headers even for local cache reads; its agent registry must never contact the Hub.
# Set this before optional imports cache the flag, without blocking explicit model downloads.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

# ONNX Runtime 1.30's macOS build carries a Microsoft telemetry uploader; in a full film run it still
# connected out although every session was opened after disable_telemetry_events() (#2217). The
# runtime reads this variable itself, so it is set before anything can load the runtime.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

__author__ = "Immich Memories Contributors"

# WHY first: a run's `startup` span measures from here, so it must precede the config imports.
from immich_memories import process_start  # noqa: F401, I001

# WHY before the config imports: torch, NumPy and OpenCV size their OpenMP and BLAS pools
# when they load, from the host's cores rather than the container's CPU limit (#2683).
from immich_memories.processing.ffmpeg_threads import limit_native_pools  # noqa: I001

limit_native_pools()

from immich_memories._version import __version__  # noqa: E402
from immich_memories.config import Config, get_config  # noqa: E402

__all__ = ["Config", "get_config", "__version__"]
