"""Put a people document into the test's default store, the way `people import` would."""

from __future__ import annotations

from typing import Any

import yaml

from immich_memories.db import Store, open_store
from immich_memories.people.transfer import import_document


def seed_people(document: dict[str, Any] | str) -> Store:
    """The default store holding `document` (a mapping or YAML text) as its registry."""
    store = open_store()
    import_document(store, yaml.safe_load(document) if isinstance(document, str) else document)
    return store
