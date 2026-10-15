"""The sign-in an install gets when nobody configured one: a generated password, kept as a hash.

Authentication is on unless the operator turns it off. With basic sign-in and no password
configured, the first start generates a password, stores only its scrypt hash beside the
config file, and prints it once, in the log of that start. No HTTP route ever returns it.
Later starts read the hash and never print it again. `immich-memories auth reset-password`
writes a new one and prints it once to the terminal; the hash is part of every session's
fingerprint, so the sessions signed in with the old one end.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from pathlib import Path

from immich_memories.config.models.auth import AuthConfig
from immich_memories.logging_config import install_secret_redaction
from immich_memories.security import write_secret_file

logger = logging.getLogger(__name__)

LOGIN_FILE = "generated-login.json"
# RFC 7914's interactive parameters: about 16 MiB and a few dozen milliseconds per check.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def login_path(state_dir: Path) -> Path:
    """Where the generated password's hash lives: beside the config file."""
    return state_dir / LOGIN_FILE


def _digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)


def _stored(path: Path) -> tuple[bytes, bytes] | None:
    """The salt and hash on disk, or None when there is no readable login file."""
    try:
        record = json.loads(path.read_text())
        return bytes.fromhex(record["salt"]), bytes.fromhex(record["hash"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def reset_generated_login(path: Path) -> str:
    """Generate a new password, store only its hash, and return it for the caller to show once."""
    password = secrets.token_urlsafe(18)
    salt = secrets.token_bytes(16)
    record = {
        "scheme": "scrypt",
        **_SCRYPT,
        "salt": salt.hex(),
        "hash": _digest(password, salt).hex(),
    }
    write_secret_file(path, json.dumps(record))
    return password


def ensure_generated_login(path: Path) -> str | None:
    """Generate and store a password when none is stored; return it only when it is new."""
    if _stored(path) is not None:
        return None
    return reset_generated_login(path)


def announce_generated_login(auth: AuthConfig, state_dir: Path) -> None:
    """On a start that needs one, make the password and say it once in the log."""
    if not auth.generates_login:
        return
    path = login_path(state_dir)
    password = ensure_generated_login(path)
    if password is None:
        logger.info(
            "Sign-in uses the password generated on first start (user %s). Lost it? "
            "Run `immich-memories auth reset-password` for a new one",
            auth.sign_in_username,
        )
        return
    logger.warning(
        "\n\n  Sign in to Immich Memories with\n    username: %s\n    password: %s\n\n"
        "  This password is shown once, here. Only its hash is kept, in %s.\n"
        "  `immich-memories auth reset-password` makes a new one. Set auth.username and "
        "auth.password to choose your own, or auth.enabled: false to run without sign-in.\n",
        auth.sign_in_username,
        password,
        path,
    )
    # Shown once: from here on the log filter strips it from every line.
    install_secret_redaction((password,))


def generated_credentials_match(username: str, password: str, auth: AuthConfig, path: Path) -> bool:
    """Check a sign-in against the stored hash, in constant time for the username."""
    stored = _stored(path)
    username_ok = secrets.compare_digest(
        username.encode("utf-8"), auth.sign_in_username.encode("utf-8")
    )
    if stored is None:
        return False
    salt, expected = stored
    return hmac.compare_digest(_digest(password, salt), expected) and username_ok


def generated_login_digest(path: Path) -> str:
    """The stored hash, for the session fingerprint: a new password ends the old sessions."""
    stored = _stored(path)
    return stored[1].hex() if stored else ""
