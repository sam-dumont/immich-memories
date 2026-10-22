"""The HTTP answers worth another try, shared by the Immich client and pinned downloads.

A 429 or a 5xx says "not now"; a 404 or a 403 answers the same every time.
"""

from __future__ import annotations

TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
