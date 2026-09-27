"""Durable, sanitized notification delivery health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store, from_db, open_store, to_db, upsert
from immich_memories.db.tables import notification_health


class NotificationFailureCategory(StrEnum):
    """Stable failure classes safe to expose through status endpoints."""

    UNAVAILABLE = "unavailable"
    AUTH = "authentication"
    QUOTA = "quota"
    PROVIDER_REJECTED = "provider_rejected"
    TRANSPORT = "transport"

    @property
    def message(self) -> str:
        """Return a bounded diagnostic that cannot contain provider response data."""
        return {
            self.UNAVAILABLE: "Notification support is not installed",
            self.AUTH: "Notification provider rejected configured credentials",
            self.QUOTA: "Notification provider quota or rate limit reached",
            self.PROVIDER_REJECTED: "Notification provider rejected the delivery",
            self.TRANSPORT: "Notification transport failed",
        }[self]


@dataclass(frozen=True)
class NotificationHealth:
    """The singleton notification health record."""

    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    failure_category: NotificationFailureCategory | None
    failure_message: str | None

    def cooldown_until(self, cooldown_hours: int) -> datetime | None:
        """Return the active failure cooldown boundary, if any."""
        if self.last_failure_at is None:
            return None
        if self.last_success_at is not None and self.last_success_at >= self.last_failure_at:
            return None
        return self.last_failure_at + timedelta(hours=max(0, cooldown_hours))

    def is_cooling_down(self, cooldown_hours: int, *, now: datetime | None = None) -> bool:
        """Return whether a newer failure still suppresses normal delivery attempts."""
        until = self.cooldown_until(cooldown_hours)
        return until is not None and (now or datetime.now(tz=UTC)) < until

    def to_dict(
        self,
        *,
        cooldown_hours: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Serialize only stable, credential-free health fields."""
        until = self.cooldown_until(cooldown_hours)
        return {
            "last_attempt_at": (
                self.last_attempt_at.isoformat() if self.last_attempt_at is not None else None
            ),
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at is not None else None
            ),
            "last_failure_at": (
                self.last_failure_at.isoformat() if self.last_failure_at is not None else None
            ),
            "failure_category": (
                self.failure_category.value if self.failure_category is not None else None
            ),
            "failure_message": self.failure_message,
            "cooldown_active": self.is_cooling_down(cooldown_hours, now=now),
            "cooldown_until": until.isoformat() if until is not None else None,
            "cooldown_hours": cooldown_hours,
        }


class NotificationStateStore:
    """Read and update notification delivery health in the store."""

    def __init__(self, store: Store | None = None):
        self.store = store or open_store()

    def get(self) -> NotificationHealth | None:
        """Return the singleton health row, or None before the first attempt."""
        with self.store.connect() as conn:
            row = (
                conn.execute(sa.select(notification_health).where(notification_health.c.id == 1))
                .mappings()
                .first()
            )
        if row is None:
            return None
        category = row["failure_category"]
        return NotificationHealth(
            last_attempt_at=from_db(row["last_attempt_at"]),
            last_success_at=from_db(row["last_success_at"]),
            last_failure_at=from_db(row["last_failure_at"]),
            failure_category=(NotificationFailureCategory(category) if category else None),
            failure_message=row["failure_message"],
        )

    def is_cooling_down(self, cooldown_hours: int, *, now: datetime | None = None) -> bool:
        """Return whether normal notifications should currently be suppressed."""
        health = self.get()
        return health.is_cooling_down(cooldown_hours, now=now) if health is not None else False

    def _record(self, row: dict[str, Any]) -> NotificationHealth:
        with self.store.begin() as conn:
            upsert(conn, notification_health, [{"id": 1} | row], ["id"], update=list(row))
        health = self.get()
        assert health is not None
        return health

    def record_success(self, *, now: datetime | None = None) -> NotificationHealth:
        """Record successful delivery; retained failure history becomes inactive."""
        attempted_at = to_db(now or datetime.now(tz=UTC))
        return self._record({"last_attempt_at": attempted_at, "last_success_at": attempted_at})

    def record_failure(
        self,
        category: NotificationFailureCategory,
        *,
        now: datetime | None = None,
    ) -> NotificationHealth:
        """Record one generic failure class without accepting raw provider text."""
        attempted_at = to_db(now or datetime.now(tz=UTC))
        return self._record(
            {
                "last_attempt_at": attempted_at,
                "last_failure_at": attempted_at,
                "failure_category": category.value,
                "failure_message": category.message,
            }
        )
