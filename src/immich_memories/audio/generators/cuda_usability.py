"""Check CUDA execution before automatically routing local audio models."""

import logging

logger = logging.getLogger(__name__)


def cuda_is_usable() -> bool:
    """Require a working kernel and synchronization, not just a CUDA driver."""
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        probe = torch.ones(1, device="cuda")
        try:
            probe.add_(1)
            torch.cuda.synchronize()
        finally:
            del probe
        return True
    except (ImportError, RuntimeError):
        logger.warning("CUDA execution unavailable; automatic local audio will use CPU")
        return False
