"""Bank semantic episode readings by full membership and producer identity."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.db import Store, now_db
from immich_memories.db.tables import editorial_episode_readings, editorial_episode_refusals
from immich_memories.store.batches import bank_rows, in_chunks

logger = logging.getLogger(__name__)
_KEY = ("group_id", "producer_key", "evidence_key")


@dataclass(frozen=True)
class EpisodeReadingProducer:
    """Everything that can change the meaning produced for an episode."""

    model_id: str
    prompt_version: str
    schema_version: str
    annotation_renderer_version: str
    annotation_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        scalar_parts = (
            self.model_id,
            self.prompt_version,
            self.schema_version,
            self.annotation_renderer_version,
        )
        if any(not part.strip() for part in scalar_parts):
            raise ValueError("episode reading producer fields cannot be blank")
        if any(not version.strip() for version in self.annotation_versions):
            raise ValueError("annotation producer versions cannot be blank")
        if len(self.annotation_versions) != len(set(self.annotation_versions)):
            raise ValueError("annotation producer versions must be unique")

    def key(self) -> str:
        """Return a path- and credential-free identity for this exact contract."""
        material = {
            "identity_version": "episode-reading-producer-v1",
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "annotation_renderer_version": self.annotation_renderer_version,
            "annotation_versions": sorted(self.annotation_versions),
        }
        encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EpisodeReadingIdentity:
    """One canonical episode under one exact reading contract."""

    group_id: str
    producer_key: str
    evidence_key: str

    def __post_init__(self) -> None:
        if (
            not self.group_id.strip()
            or not self.producer_key.strip()
            or not self.evidence_key.strip()
        ):
            raise ValueError("episode reading identity cannot be blank")

    @classmethod
    def from_annotations(
        cls,
        *,
        group_id: str,
        producer_key: str,
        annotation_lines: Mapping[str, str],
    ) -> EpisodeReadingIdentity:
        """Key the exact complete text evidence independently of mapping order."""
        if not annotation_lines or any(
            not asset_id.strip() or not line.strip() for asset_id, line in annotation_lines.items()
        ):
            raise ValueError("episode identity needs complete rendered annotation lines")
        encoded = json.dumps(
            sorted(annotation_lines.items()),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            group_id=group_id,
            producer_key=producer_key,
            evidence_key=hashlib.sha256(encoded).hexdigest(),
        )


@dataclass(frozen=True)
class EpisodeRepresentative:
    """An episode member that carries one distinct part of its meaning.

    The same row shape carries a notable moment: which picture, and what it is a record of.
    """

    asset_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.reason.strip():
            raise ValueError("episode representative needs an asset and reason")


@dataclass(frozen=True)
class EpisodeCullDecision:
    """A typed Cull bucket attached to one member of the episode."""

    asset_id: str
    bucket: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.bucket.strip():
            raise ValueError("episode cull decision needs an asset and bucket")


@dataclass(frozen=True)
class BankedEpisodeReading:
    """Reusable meaning for one complete canonical episode."""

    identity: EpisodeReadingIdentity
    full_asset_ids: tuple[str, ...]
    what_happened: str
    representatives: tuple[EpisodeRepresentative, ...]
    cull_decisions: tuple[EpisodeCullDecision, ...]
    # What the reading says is worth a record of its own, and why. A reading that named
    # none is an episode nothing stood out in, not an unread one.
    notable_moments: tuple[EpisodeRepresentative, ...] = ()

    def __post_init__(self) -> None:
        members = set(self.full_asset_ids)
        if not members or len(members) != len(self.full_asset_ids):
            raise ValueError("episode reading needs unique full membership")
        if not self.what_happened.strip() or not self.representatives:
            raise ValueError("episode reading needs meaning and a representative")
        referenced = {
            *(representative.asset_id for representative in self.representatives),
            *(decision.asset_id for decision in self.cull_decisions),
            *(moment.asset_id for moment in self.notable_moments),
        }
        if not referenced.issubset(members):
            raise ValueError("episode reading may reference only full episode members")


class EpisodeReadingStore:
    """Persist immutable episode readings in the store."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def remember(self, readings: Iterable[BankedEpisodeReading]) -> None:
        """Keep complete readings; an existing identity is never rerolled."""
        answered_at = now_db()
        rows = [_row_for(reading) | {"answered_at": answered_at} for reading in readings]
        if not rows:
            return
        try:
            bank_rows(self._store, editorial_episode_readings, rows, keys=_KEY, update=())
        except (OSError, SQLAlchemyError) as exc:
            logger.debug("Episode reading store unwritable (%s): reading not kept", exc)

    def readings_for(
        self,
        identities: Sequence[EpisodeReadingIdentity],
    ) -> dict[str, BankedEpisodeReading]:
        """Return readings matching current membership, producer, and evidence."""
        t = editorial_episode_readings
        try:
            rows = self._matching(
                sa.select(
                    t.c.group_id,
                    t.c.producer_key,
                    t.c.evidence_key,
                    t.c.full_asset_ids,
                    t.c.what_happened,
                    t.c.representatives,
                    t.c.cull_decisions,
                    t.c.notable_moments,
                ),
                t,
                identities,
            )
        except (OSError, SQLAlchemyError) as exc:
            logger.debug("Episode reading store unreadable (%s): treating as cold", exc)
            return {}
        recalled: dict[str, BankedEpisodeReading] = {}
        for row in rows:
            try:
                reading = _reading_from(row)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.debug("Skipping invalid banked episode reading %s", row[0])
                continue
            recalled[reading.identity.group_id] = reading
        return recalled

    def remember_refusals(self, refusals: Iterable[tuple[EpisodeReadingIdentity, str]]) -> None:
        """Keep "this exact question could not be read" so it is asked once, not every run.

        Only a refusal the same question would earn again belongs here: a reader that answered
        and whose answer could not be used, or evidence too large to ask about. A provider that
        was unreachable has refused nothing, and the caller keeps those out.
        """
        answered_at = now_db()
        rows = [
            {
                "group_id": identity.group_id,
                "producer_key": identity.producer_key,
                "evidence_key": identity.evidence_key,
                "reason": reason,
                "answered_at": answered_at,
            }
            for identity, reason in refusals
            if reason.strip()
        ]
        if not rows:
            return
        try:
            bank_rows(self._store, editorial_episode_refusals, rows, keys=_KEY, update=())
        except (OSError, SQLAlchemyError) as exc:
            logger.debug("Episode refusal store unwritable (%s): refusal not kept", exc)

    def refusals_for(self, identities: Sequence[EpisodeReadingIdentity]) -> dict[str, str]:
        """The episodes this exact contract already failed to read, and why."""
        t = editorial_episode_refusals
        try:
            rows = self._matching(sa.select(t.c.group_id, t.c.reason), t, identities)
        except (OSError, SQLAlchemyError) as exc:
            logger.debug("Episode refusal store unreadable (%s): treating as cold", exc)
            return {}
        return {str(group_id): str(reason) for group_id, reason in rows}

    def _matching(
        self, query: sa.Select, table: sa.Table, identities: Sequence[EpisodeReadingIdentity]
    ) -> list[sa.Row]:
        ordered = list(dict.fromkeys(identities))
        key = sa.tuple_(*(table.c[name] for name in _KEY))
        rows: list[sa.Row] = []
        with self._store.connect() as connection:
            for chunk in in_chunks(connection, ordered, per_row=3):
                wanted = [(i.group_id, i.producer_key, i.evidence_key) for i in chunk]
                rows.extend(connection.execute(query.where(key.in_(wanted))))
        return rows


def _row_for(reading: BankedEpisodeReading) -> dict[str, str]:
    def pairs(items: Iterable[EpisodeRepresentative]) -> str:
        return json.dumps(
            [{"asset_id": item.asset_id, "reason": item.reason} for item in items],
            separators=(",", ":"),
        )

    return {
        "group_id": reading.identity.group_id,
        "producer_key": reading.identity.producer_key,
        "evidence_key": reading.identity.evidence_key,
        "full_asset_ids": json.dumps(reading.full_asset_ids, separators=(",", ":")),
        "what_happened": reading.what_happened,
        "representatives": pairs(reading.representatives),
        "cull_decisions": json.dumps(
            [
                {"asset_id": decision.asset_id, "bucket": decision.bucket}
                for decision in reading.cull_decisions
            ],
            separators=(",", ":"),
        ),
        "notable_moments": pairs(reading.notable_moments),
    }


def _reading_from(row: Sequence[object]) -> BankedEpisodeReading:
    representatives = json.loads(str(row[5]))
    cull_decisions = json.loads(str(row[6]))
    return BankedEpisodeReading(
        identity=EpisodeReadingIdentity(
            group_id=str(row[0]),
            producer_key=str(row[1]),
            evidence_key=str(row[2]),
        ),
        full_asset_ids=tuple(str(asset_id) for asset_id in json.loads(str(row[3]))),
        what_happened=str(row[4]),
        representatives=tuple(
            EpisodeRepresentative(asset_id=str(item["asset_id"]), reason=str(item["reason"]))
            for item in representatives
        ),
        cull_decisions=tuple(
            EpisodeCullDecision(asset_id=str(item["asset_id"]), bucket=str(item["bucket"]))
            for item in cull_decisions
        ),
        notable_moments=tuple(
            EpisodeRepresentative(asset_id=str(item["asset_id"]), reason=str(item["reason"]))
            for item in json.loads(str(row[7]))
        ),
    )
