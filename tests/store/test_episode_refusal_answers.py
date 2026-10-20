"""#2682: a refused episode keeps what the reader answered, so the refusal can be explained."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from immich_memories.db import downgrade, upgrade
from immich_memories.db.tables import editorial_episode_refusals
from immich_memories.store.episode_readings import (
    EpisodeReadingIdentity,
    EpisodeReadingStore,
    EpisodeRefusal,
)

IDENTITY = EpisodeReadingIdentity("episode-1", "producer", "evidence")


def _stored(store) -> list[tuple[str, str | None]]:
    with store.connect() as connection:
        return [
            (row.reason, row.answer_excerpt)
            for row in connection.execute(
                sa.select(
                    editorial_episode_refusals.c.reason,
                    editorial_episode_refusals.c.answer_excerpt,
                )
            )
        ]


def test_a_refusal_keeps_the_answer_it_was_filed_over(store):
    bank = EpisodeReadingStore(store)

    bank.remember_refusals([EpisodeRefusal(IDENTITY, "the answer had no entry", '{"episodes":[]}')])

    assert bank.refusals_for([IDENTITY]) == {"episode-1": "the answer had no entry"}
    assert _stored(store) == [("the answer had no entry", '{"episodes":[]}')]


def test_a_refusal_filed_before_the_upgrade_stays_and_has_no_answer(store):
    downgrade(store, "0016_phase_event_rows")
    with store.begin() as connection:
        # Only the columns the older schema has: the insert names nothing else.
        connection.execute(
            sa.insert(editorial_episode_refusals).values(
                group_id="episode-1",
                producer_key="producer",
                evidence_key="evidence",
                reason="text episode response was missing or invalid",
                answered_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    upgrade(store)

    assert EpisodeReadingStore(store).refusals_for([IDENTITY]) == {
        "episode-1": "text episode response was missing or invalid"
    }
    assert _stored(store) == [("text episode response was missing or invalid", None)]
