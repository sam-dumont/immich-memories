"""What a film may use: the discovery pool for one window, album or household.

A pool is resolved once per run, before the editor is built, and the editor never refetches it.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "album",
    "album_index",
    "event_scope",
    "household",
    "live_photos",
    "person_presence",
    "person_resolution",
    "pool",
    "snapshot",
    "thumbnail_prefetch",
    "trip_discovery",
    "window_context",
]
