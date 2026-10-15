"""Whether the Apple Vision framework can be loaded on this Mac, for the hardware report."""

from __future__ import annotations

import logging
import platform
from functools import lru_cache

logger = logging.getLogger(__name__)

# Check if we're on macOS
IS_MACOS = platform.system() == "Darwin"

# Lazy imports for macOS frameworks
_vision_available = None
_Vision = None
_Quartz = None


def _check_vision_available() -> bool:
    """Check if Vision framework is available."""
    global _vision_available, _Vision, _Quartz

    if _vision_available is not None:
        return _vision_available

    if not IS_MACOS:
        _vision_available = False
        return False

    try:
        import Quartz
        import Vision

        _Vision = Vision
        _Quartz = Quartz
        _vision_available = True
        logger.debug("Apple Vision framework available")
        return True
    except ImportError as e:
        logger.debug(f"Vision framework not available: {e}")
        _vision_available = False
        return False


@lru_cache(maxsize=1)
def is_vision_available() -> bool:
    """Check if Apple Vision framework is available.

    Returns:
        True if Vision framework can be used.
    """
    return _check_vision_available()
