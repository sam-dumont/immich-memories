"""Whether a signed session cookie still stands: its age, its sign-in rules, and sign-outs since.

The cookie is signed, not stored, so on its own it stays good until it expires: a copy taken
before a sign-out would still open the app. Two stamps close that. A generation counter kept
in the store (one per username, one for everyone) is bumped on sign-out; a cookie carrying an
older count is refused. A fingerprint of the sign-in rules (provider, password, OIDC client
and allow-list, trusted proxies) is keyed with the session secret; changing any of them in
config.yaml or the environment ends every session at once, with no counter to bump.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from immich_memories.config_loader import Config
from immich_memories.config_models_auth import AuthConfig
from immich_memories.db import now_db, open_store
from immich_memories.db.tables.session_generations import session_generations
from immich_memories.web.auth import set_session

logger = logging.getLogger(__name__)

# One integer row per key: `*` for everyone, a username for one user. A session's
# generation is the sum of its user's count and everyone's; both only grow, so any bump
# changes the sum. The bump is a single INSERT .. ON CONFLICT statement, so two
# concurrent sign-outs each land their own increment even on PostgreSQL.
_EVERYONE = "*"


def session_generation(config: Config, username: str) -> int:
    """The generation a cookie for `username` has to carry to be current."""
    with open_store(config).connect() as connection:
        result = connection.execute(
            sa.select(session_generations.c.key, session_generations.c.generation).where(
                session_generations.c.key.in_([_EVERYONE, username])
            )
        )
        counts = {str(row["key"]): int(row["generation"]) for row in result.mappings()}
    return counts.get(_EVERYONE, 0) + counts.get(username, 0)


def end_sessions(config: Config, username: str | None) -> None:
    """Refuse every cookie issued so far to `username`, or to everyone when it is None."""
    key = _EVERYONE if username is None else username
    with open_store(config).begin() as connection:
        dialect = postgresql if connection.dialect.name == "postgresql" else sqlite
        statement = dialect.insert(session_generations)
        statement = statement.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "generation": session_generations.c.generation + 1,
                "updated_at": statement.excluded.updated_at,
            },
        )
        connection.execute(statement, [{"key": key, "generation": 1, "updated_at": now_db()}])


def auth_fingerprint(auth: AuthConfig, secret: str) -> str:
    """A keyed digest of the sign-in rules; any change to them ends every session.

    Keyed with the session secret so the readable cookie does not carry a plain hash of
    the password.
    """
    rules = [
        auth.provider,
        auth.username,
        auth.password,
        auth.issuer_url,
        auth.client_id,
        sorted(auth.allowed_emails),
        sorted(auth.allowed_domains),
        auth.user_header,
        sorted(auth.trusted_proxies),
    ]
    message = json.dumps(rules).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def start_session(
    session: MutableMapping[str, object],
    *,
    config: Config,
    secret: str,
    username: str,
    provider: str,
    email: str = "",
) -> None:
    """Sign `username` in, stamped with the current generation and sign-in rules."""
    set_session(session, username=username, provider=provider, email=email)
    session["session_generation"] = session_generation(config, username)
    session["auth_fingerprint"] = auth_fingerprint(config.auth, secret)


def session_expired(session: Mapping[str, Any], ttl_hours: int) -> bool:
    """Whether the session is older than `auth.session_ttl_hours`."""
    started = session.get("authenticated_at")
    if not started:
        return False
    return datetime.now(UTC) > datetime.fromisoformat(str(started)) + timedelta(hours=ttl_hours)


def session_current(session: Mapping[str, Any], config: Config, secret: str) -> bool:
    """Whether this session is signed in and still stands: in time, same rules, no sign-out."""
    if not session.get("authenticated") or session_expired(session, config.auth.session_ttl_hours):
        return False
    fingerprint = str(session.get("auth_fingerprint", ""))
    if not hmac.compare_digest(fingerprint, auth_fingerprint(config.auth, secret)):
        return False
    try:
        generation = session_generation(config, str(session.get("username", "")))
    except Exception:  # WHY: no readable store means no proof the session survived a sign-out
        logger.warning("Session check could not read the store; treating the session as ended")
        return False
    return session.get("session_generation") == generation
