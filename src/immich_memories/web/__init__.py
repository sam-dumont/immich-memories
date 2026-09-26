"""The web client's server side: a versioned JSON API over the engine the CLI drives."""

from immich_memories.web.app import mount_web

__all__ = ["mount_web"]
