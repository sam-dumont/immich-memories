"""Caption origins kept beside immutable description rows, outside reader identities."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.analysis.editorial_description_contract import DESCRIPTION_MODEL
from immich_memories.analysis.llm_caption_identity import LLM_CAPTION_PREFIX
from immich_memories.db import Store
from immich_memories.db.tables import caption_provenance, descriptions
from immich_memories.store.batches import id_in, in_chunks, insert_rows
from immich_memories.store.caption_selection import selected_captions

# Measured on ggml-org/llama.cpp:server build b10920: /v1/models answers
# `created` from the current clock, so it ticks on every probe. Keeping it would
# file every prepare run under a new origin and make the distinct count
# meaningless. mlxcel answers a fixed value, so this cannot be decided per server.
VOLATILE_SERVED_KEYS = frozenset({"created"})

_FACT_LIMIT = 128


def served_facts(row: Mapping[str, object]) -> dict[str, str]:
    """Everything the endpoint says about the weights it loaded, minus what ticks.

    The served `/models` row is the only thing in the probe that came from the
    model file rather than from configuration. llama.cpp puts `owned_by`,
    `meta.n_params`, `meta.size` and `meta.ftype` there; mlxcel puts none of them.
    """
    facts: dict[str, str] = {}
    for key, value in row.items():
        # `id` is the alias the origin already carries and `object` is the
        # OpenAI envelope's own word for itself; neither says anything about a build.
        if key in VOLATILE_SERVED_KEYS or key in {"id", "object"}:
            continue
        if isinstance(value, Mapping):
            facts |= {
                f"{key}.{inner}": str(nested)[:_FACT_LIMIT]
                for inner, nested in value.items()
                if isinstance(nested, str | int | float | bool)
            }
        elif isinstance(value, str | int | float | bool):
            facts[key] = str(value)[:_FACT_LIMIT]
        elif isinstance(value, Sequence) and all(isinstance(item, str) for item in value):
            facts[key] = ",".join(value)[:_FACT_LIMIT]
    # An empty answer is not a fact, and llama.cpp sends an empty `tags` list.
    return {key: value for key, value in facts.items() if value}


@dataclass(frozen=True)
class CaptionOrigin:
    """What produced one caption: the alias, the address, and what the weights answered."""

    model_id: str
    endpoint: str
    artifact_id: str = ""
    served: dict[str, str] = field(default_factory=dict)
    control_digest: str = ""

    def __post_init__(self) -> None:
        parts = urlsplit(self.endpoint)
        clean = parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1], query="", fragment="")
        object.__setattr__(self, "endpoint", clean.geturl())

    # Counting distinct origins needs this type as a dict key, and the generated
    # __hash__ raises on the `served` mapping.
    def __hash__(self) -> int:
        return hash(self.key())

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


# A caption banked before origins were recorded at all: never attributed to
# whatever server happens to be configured now.
UNRECORDED = {"status": "unknown"}
# The asset carries no caption row, so nothing produced one.
UNCAPTIONED = {"status": "none"}


def remember_origins(
    connection: Connection, asset_ids: Sequence[str], model: str, origin: CaptionOrigin
) -> None:
    """One origin for a batch of captions, in the caller's transaction."""
    key = origin.key()
    insert_rows(
        connection,
        caption_provenance,
        [{"asset_id": asset_id, "model": model, "origin": key} for asset_id in asset_ids],
    )


def group_origins(
    asset_ids: Sequence[str], recorded: Mapping[str, str | None]
) -> dict[str, object]:
    """Fold per-asset origins into the distinct ones, largest group first.

    A per-asset map repeats one identical origin once per picture: 9.1 MB for the
    48,689-caption bank on this machine, in a file the story page parses whole to
    read one field. The distinct origins are the answer to "is this bank mixed",
    and `by_asset` names only the assets outside the largest group, so the
    exception list is bounded by the size of the seam rather than by the library.
    """
    members: dict[str, list[str]] = {}
    shapes: dict[str, dict] = {}
    for asset_id in asset_ids:
        if asset_id not in recorded:
            origin = UNCAPTIONED.copy()
        elif raw := recorded[asset_id]:
            origin = json.loads(raw)
        else:
            origin = UNRECORDED.copy()
        key = json.dumps(origin, sort_keys=True)
        shapes.setdefault(key, origin)
        members.setdefault(key, []).append(asset_id)
    if not members:
        return {}
    order = sorted(members, key=lambda key: (-len(members[key]), key))
    return {
        "origins": [shapes[key] | {"assets": len(members[key])} for key in order],
        "by_asset": {
            asset_id: index for index, key in enumerate(order) if index for asset_id in members[key]
        },
    }


def origins_for(store: Store, asset_ids: Sequence[str], model: str) -> dict[str, object]:
    """Group this run's assets by what produced their caption; old rows stay unknown."""
    wanted = tuple(dict.fromkeys(asset_ids))
    llm = model.startswith(LLM_CAPTION_PREFIX)
    d, p = descriptions, caption_provenance
    recorded: dict[str, Any] = {}
    with store.connect() as connection:
        chosen = (
            {
                a: caption.model
                for a, caption in selected_captions(connection, wanted, model).items()
            }
            if llm
            else dict.fromkeys(wanted, model)
        )
        for chunk in in_chunks(connection, wanted):
            rows = connection.execute(
                sa.select(d.c.asset_id, d.c.model, p.c.origin)
                .select_from(
                    d.outerjoin(p, sa.and_(d.c.asset_id == p.c.asset_id, d.c.model == p.c.model))
                )
                .where(
                    d.c.model.in_((model, DESCRIPTION_MODEL if llm else model)),
                    id_in(connection, d.c.asset_id, chunk),
                )
            )
            recorded.update(
                (str(asset), origin)
                for asset, producer, origin in rows
                if chosen.get(str(asset)) == producer
            )
    return group_origins(wanted, recorded)
