"""Storage failures that callers can explain without printing private paths."""

import errno
import sqlite3


def storage_failure_message(error: BaseException) -> str | None:
    """Explain a full filesystem or quota without exposing the failed file name."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if (
            (isinstance(current, OSError) and current.errno in (errno.ENOSPC, errno.EDQUOT))
            or getattr(current, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
            or getattr(current, "sqlstate", None) == "53100"
        ):
            return (
                "Storage is full or its quota is exhausted. Expand the cache/output volume "
                "or database storage, or free space by clearing disposable caches while the app "
                "is idle, then retry. Do not delete the store or the whole data volume."
            )
        current = current.__cause__ or current.__context__
    return None
