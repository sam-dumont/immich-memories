"""GET /stacks, once per account per run, read into one member -> primary map.

`stack.read` is optional (`docs/run/docker.md`): a key without it, or a server
too old to have stacks at all, answers 403 or 404. Either way the run goes on
exactly as it did before Immich 3.3 -- no stack folding -- with one warning
per account rather than a failed run over an optional read.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from immich_memories.api.accounts import OpenAccount
from immich_memories.api.immich import ImmichAPIError

logger = logging.getLogger(__name__)


def discover_stack_map(opened: Mapping[str, OpenAccount]) -> dict[str, str]:
    """Every opened account's stacks, folded into one member id -> primary id map."""
    stack_of: dict[str, str] = {}
    for name, account in opened.items():
        try:
            stacks = account.client.get_stacks()
        except ImmichAPIError as error:
            logger.warning(
                "Could not read stacks for account %r (%s); stack folding is skipped for it. "
                "Add stack.read to the key, or ignore this on a pre-3.3 server.",
                name,
                error,
            )
            continue
        for stack in stacks:
            for member in stack.assets:
                if member.id != stack.primary_asset_id:
                    stack_of[member.id] = stack.primary_asset_id
    return stack_of
