"""The settings layer in the store: what the UI and the CLI save, below env and config.yaml.

One row per runtime key path (`llm.model`, `automation.cooldown_hours`). Only saved keys
have a row; a default is never written. Secrets are sealed with Fernet under a key derived
from `IMMICH_MEMORIES_SECRET_KEY`, so the raw column never holds the plaintext.

Bootstrap keys (`database.*`) are never stored or read here: the store's location has to
be known before the store opens.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from immich_memories.db import (
    Store,
    StoreLocation,
    now_db,
    open_store,
    resolve_location,
    upsert,
)
from immich_memories.db.tables import settings
from immich_memories.security import CREDENTIAL_FIELD_NAMES

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

SECRET_KEY_ENV = "IMMICH_MEMORIES_SECRET_KEY"  # noqa: S105 — a variable name, not a secret
MIN_SECRET_KEY_LENGTH = 32
SKIP_STORED_SETTINGS_ENV = "IMMICH_MEMORIES_SKIP_STORED_SETTINGS"

# Beyond the credential fields: notification URLs embed tokens (apprise://user:pass@host).
_SECRET_FIELD_NAMES = CREDENTIAL_FIELD_NAMES | {"api_keys", "secret", "token", "urls"}
# Maps saved as one row whose entries carry credentials: sealed whole, like `urls`.
_SECRET_MAPS = frozenset({"immich.accounts"})
# Fixed on purpose: the same IMMICH_MEMORIES_SECRET_KEY must open the same rows next run.
_HKDF_SALT = b"immich-memories/settings/v1"


class SettingsUnavailable(RuntimeError):
    """A store is configured or present, but its saved settings cannot be read."""


class SecretKeyError(RuntimeError):
    """A secret cannot be stored or read: IMMICH_MEMORIES_SECRET_KEY is missing or too short."""


def is_secret_key(key: str) -> bool:
    """Whether a runtime key path holds a credential and is kept encrypted."""
    return key in _SECRET_MAPS or key.rsplit(".", 1)[-1] in _SECRET_FIELD_NAMES


def is_bootstrap_key(key: str) -> bool:
    """Keys read before the store opens, so they can never come from it."""
    return key == "database" or key.startswith("database.")


def secret_key_from_env() -> str | None:
    """The configured secret key, or None when it is unset or blank."""
    return os.environ.get(SECRET_KEY_ENV) or None


def _fernet(secret_key: str | None) -> Fernet:
    if not secret_key:
        raise SecretKeyError(
            f"{SECRET_KEY_ENV} is not set, so secrets cannot be stored in the database. "
            "Set it (for example `openssl rand -base64 32`), or set the secret in the "
            "environment or config.yaml instead."
        )
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise SecretKeyError(
            f"{SECRET_KEY_ENV} must be at least {MIN_SECRET_KEY_LENGTH} characters "
            "(`openssl rand -base64 32` prints one)."
        )
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=b"settings-fernet"
    ).derive(secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def nest_dotted(flat: Mapping[str, Any]) -> dict[str, Any]:
    """Turn `{"llm.model": x}` into `{"llm": {"model": x}}`."""
    nested: dict[str, Any] = {}
    for key, value in flat.items():
        *parents, leaf = key.split(".")
        holder = nested
        for part in parents:
            holder = holder.setdefault(part, {})
        holder[leaf] = value
    return nested


class SettingsStore:
    """Read and write the saved settings of one store.

    Values are JSON-compatible; the caller validates them against the config schema first.
    Writing a secret without a usable `secret_key` raises `SecretKeyError`.
    """

    def __init__(self, store: Store, secret_key: str | None) -> None:
        self._store = store
        self._secret_key = secret_key

    def save(self, values: Mapping[str, Any]) -> None:
        """Upsert every key in one transaction; nothing is written when one key is refused."""
        now = now_db()
        rows = [self._row(key, value, now) for key, value in values.items()]
        if not rows:
            return
        with self._store.begin() as conn:
            upsert(conn, settings, rows, keys=("key",))

    def delete(self, keys: Iterable[str]) -> None:
        """Forget saved keys, so they fall back to their default."""
        wanted = list(keys)
        if not wanted:
            return
        with self._store.begin() as conn:
            conn.execute(sa.delete(settings).where(settings.c.key.in_(wanted)))

    def stored_keys(self) -> set[str]:
        """Every key with a row, secrets included, without decrypting anything."""
        with self._store.connect() as conn:
            return set(conn.execute(sa.select(settings.c.key)).scalars())

    def values(self) -> dict[str, Any]:
        """Every saved key and its value, secrets decrypted.

        A secret that cannot be opened (no key, or a different key) is left out with a
        warning, so the setting falls back to its default instead of stopping the app.
        """
        with self._store.connect() as conn:
            rows = conn.execute(sa.select(settings)).mappings().all()
        values: dict[str, Any] = {}
        for row in rows:
            if is_bootstrap_key(row["key"]):
                continue
            if not row["secret"]:
                values[row["key"]] = row["value"]
            elif (opened := self._open(row["key"], row["ciphertext"])) is not None:
                values[row["key"]] = opened
        return values

    def unreadable_keys(self) -> set[str]:
        """Stored secrets the current IMMICH_MEMORIES_SECRET_KEY cannot open."""
        with self._store.connect() as conn:
            rows = conn.execute(sa.select(settings).where(settings.c.secret)).mappings().all()
        return {str(row["key"]) for row in rows if not self._opens(row["ciphertext"])}

    def _opens(self, token: bytes | None) -> bool:
        try:
            _fernet(self._secret_key).decrypt(token or b"")
        except (SecretKeyError, InvalidToken):
            return False
        return True

    def _row(self, key: str, value: Any, now: Any) -> dict[str, Any]:
        if is_bootstrap_key(key):
            raise ValueError(f"{key} is read before the store opens; set it in env or config.yaml")
        if not is_secret_key(key):
            return {
                "key": key,
                "value": value,
                "secret": False,
                "ciphertext": None,
                "updated_at": now,
            }
        token = _fernet(self._secret_key).encrypt(json.dumps(value).encode())
        return {"key": key, "value": None, "secret": True, "ciphertext": token, "updated_at": now}

    def _open(self, key: str, token: bytes | None) -> Any:
        try:
            return json.loads(_fernet(self._secret_key).decrypt(token or b""))
        except (SecretKeyError, InvalidToken) as error:
            reason = "is not set" if isinstance(error, SecretKeyError) else "does not open it"
            logger.warning(
                "Ignoring the stored secret %s: %s %s. Save it again or set it in env or config.yaml.",
                key,
                SECRET_KEY_ENV,
                reason,
            )
            return None


def settings_store(config: Config, *, create: bool) -> SettingsStore | None:
    """The settings of the store `config.database` names.

    With `create=False` a SQLite store that does not exist yet is not created: it cannot
    hold settings, and loading a config must not leave a database file behind.
    """
    return _settings_at(resolve_location(config), create=create)


def _settings_at(location: StoreLocation, *, create: bool) -> SettingsStore | None:
    path = location.sqlite_path
    if not create and location.dialect_name == "sqlite" and (path is None or not path.exists()):
        return None
    return SettingsStore(open_store(location=location), secret_key_from_env())


def load_stored_settings(config: Config) -> dict[str, Any]:
    """The saved settings as runtime key paths, for the config loader's database source.

    `config` only has to carry the bootstrap `database` section. A SQLite store that does
    not exist yet is a fresh install and reads as empty. Any other store that cannot be
    read raises `SettingsUnavailable`: starting on the wrong settings is worse than not
    starting, unless the operator sets IMMICH_MEMORIES_SKIP_STORED_SETTINGS=1.
    """
    if os.environ.get(SKIP_STORED_SETTINGS_ENV) == "1":
        logger.warning("%s=1: settings saved in the database are ignored", SKIP_STORED_SETTINGS_ENV)
        return {}
    location: StoreLocation | None = None
    try:
        location = resolve_location(config)
        store = _settings_at(location, create=False)
        return store.values() if store is not None else {}
    except Exception as error:  # noqa: BLE001 -- every cause is re-raised, named
        raise SettingsUnavailable(_unavailable(location, error)) from error


def _unavailable(location: StoreLocation | None, error: BaseException) -> str:
    cause = str(getattr(error, "orig", None) or error).strip().splitlines()
    text = cause[0] if cause else type(error).__name__
    where = "the configured store"
    if location is not None:
        where = f"the store at {location}"
        if password := location.sa_url.password:
            text = text.replace(str(password), "***")
    return (
        f"The settings saved in {where} could not be read: {text}. Start or repair the "
        "database, or fix IMMICH_MEMORIES_DATABASE_URL / database.url in config.yaml. To "
        f"start without the saved settings (env, config.yaml and defaults only), set "
        f"{SKIP_STORED_SETTINGS_ENV}=1."
    )
