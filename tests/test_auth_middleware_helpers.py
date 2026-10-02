"""The session's lifetime: a sign-in lasts `auth.session_ttl_hours`, then it is over."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from immich_memories.web.session_validity import session_expired


class TestSessionLifetime:
    def test_no_authenticated_at_never_expires(self):
        assert session_expired({}, 24) is False

    def test_fresh_session_is_live(self):
        assert session_expired({"authenticated_at": datetime.now(UTC).isoformat()}, 24) is False

    def test_old_session_is_expired(self):
        started = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        assert session_expired({"authenticated_at": started}, 24) is True
