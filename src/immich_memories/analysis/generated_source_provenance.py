"""The films this app made and put back in the library, so it never films them again.

Two independent records, because neither is complete on its own: the provenance tag
Immich holds (which a library restored from a backup keeps, but which an older upload
never got), and this install's own upload receipts (which cover every upload it made,
but not one made from another machine).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from immich_memories.tracking.run_database import RunDatabase

if TYPE_CHECKING:
    from immich_memories.db import Store

logger = logging.getLogger(__name__)


def generated_source_ids(
    *, tagged: Callable[[], Iterable[str]], store: Store | None = None
) -> frozenset[str]:
    """Every id either record calls one of ours.

    The receipts are the run history's delivered asset ids. A server that refuses the tag
    query (an API key without tag scope, a version that predates tags) leaves the receipts
    answering rather than failing the run.
    """
    try:
        by_tag = frozenset(tagged())
    except (OSError, ValueError, KeyError) as error:
        logger.warning("Could not read the generated-film tag back from Immich: %s", error)
        by_tag = frozenset()
    return by_tag | RunDatabase(store).delivered_asset_ids()
