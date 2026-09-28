"""The Immich connection in Settings: which server, whether a key is stored, and a test call.

The stored key never reaches a browser, and it only ever goes to the URL it was stored with:
a different URL is taken only with a key typed for it, otherwise whoever reaches the page could
point the stored key at their own server and read it off the wire (#1212).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from immich_memories.api.immich import ImmichAPIError
from immich_memories.config_loader import Config
from immich_memories.security import sanitize_error_message
from immich_memories.settings_edit import SettingRefused, save_settings
from immich_memories.web.dependencies import Greeter, config_file, current_config, immich_greeter
from immich_memories.web.schemas import Connection, ConnectionEntry, Greeting

router = APIRouter(prefix="/api/v1/connection", tags=["settings"])

MOVED_WITHOUT_KEY = "The server URL changed: enter the API key for the new server."


def _same_server(a: str, b: str) -> bool:
    return a.strip().rstrip("/") == b.strip().rstrip("/")


def _resolved(entry: ConnectionEntry, config: Config) -> tuple[str, str]:
    """The URL and key this entry means, or 422 when it would send the stored key elsewhere."""
    url = entry.url.strip()
    typed_key = entry.api_key.strip()
    moved = not _same_server(url, config.immich.url)
    if moved and config.immich.api_key and not typed_key:
        raise HTTPException(422, MOVED_WITHOUT_KEY)
    key = typed_key or config.immich.api_key
    if not url or not key:
        raise HTTPException(422, "Please enter both URL and API key")
    return url, key


def connection_changes(config: Config, *, url: str, key: str) -> dict[str, str]:
    """The connection fields that differ from the loaded config, keyed for `save_settings`.

    An unchanged key is left out, so saving a new URL never re-stores (or needs the secret key
    for) the API key it already has.
    """
    typed = {"immich.url": url, "immich.api_key": key}
    loaded = {"immich.url": config.immich.url, "immich.api_key": config.immich.api_key}
    return {name: value for name, value in typed.items() if value != loaded[name]}


@router.get("", response_model=Connection)
def read_connection(config: Annotated[Config, Depends(current_config)]) -> Connection:
    """The server this install reads, and whether a key is stored for it."""
    return Connection(url=config.immich.url, has_key=bool(config.immich.api_key))


@router.post("/test", response_model=Greeting)
def test_connection(
    entry: ConnectionEntry,
    config: Annotated[Config, Depends(current_config)],
    greet: Annotated[Greeter, Depends(immich_greeter)],
) -> Greeting:
    """Ask the server who the key belongs to, without saving anything."""
    url, key = _resolved(entry, config)
    try:
        return Greeting(user=greet(url, key, str(config.immich.api_version)))
    except (ImmichAPIError, OSError) as error:
        raise HTTPException(502, sanitize_error_message(str(error))) from error


@router.put("", response_model=Connection)
def save_connection(
    entry: ConnectionEntry,
    config: Annotated[Config, Depends(current_config)],
    path: Annotated[Path, Depends(config_file)],
) -> Connection:
    """Save the server and key to the database, only the ones that changed.

    config.yaml and the environment are never written: a value either of them sets is refused
    with the name of what sets it, and a key needs IMMICH_MEMORIES_SECRET_KEY to be stored.
    """
    url, key = _resolved(entry, config)
    changes = connection_changes(config, url=url, key=key)
    try:
        saved = save_settings(changes, path=path) if changes else config
    except SettingRefused as refused:
        raise HTTPException(422, str(refused)) from refused
    return read_connection(saved)
