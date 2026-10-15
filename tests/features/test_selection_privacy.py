"""Feature tests for what a cut may show: personal documents.

The fixture library's scripted editor stands in for selection, so a selection promise
is checked on the production planner instead: a whole cut planned by the no-model
(NAS) route over a prepared period, read as the list of pictures the film plays.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.test_editorial_duration_planner_integration import source

_PASSPORT = "A photo of a passport on the table"


def _nas_cut(prepared, name: str) -> list[str]:
    """The pictures a no-model cut of this period plays, in order."""
    from immich_memories.analysis.film.contract import StructurePlannerPorts
    from immich_memories.analysis.stories.rule_reader import NoModelJudge, RuleStructureReader
    from immich_memories.analysis.structure.planner import plan_structure
    from immich_memories.config.loader import Config

    nas = replace(
        prepared,
        config=Config(editorial={"preparation": {"tier": "no_captions"}, "reader": "rules"}),
        artifact_dir=prepared.bank_dir.parent / name,
    )
    ports = StructurePlannerPorts(
        judge=NoModelJudge(), thumbnail_hash=lambda _: None, rules=RuleStructureReader(nas)
    )
    return [row["asset_id"] for row in plan_structure(nas, ports).plan["carriers"]]


def _photographed_document(prepared, asset_id: str):
    """The same period, with one picture read as a photographed passport."""
    line = replace(
        prepared.audience_annotations[asset_id],
        text=f"2020-05-02T08:00:00+00:00 | {_PASSPORT}",
        description=_PASSPORT,
    )
    return replace(
        prepared,
        audience_annotations=prepared.audience_annotations | {asset_id: line},
        annotations=dict(prepared.annotations) | {asset_id: line.text},
    )


@pytest.mark.feature("privacy.documents-held")
def test_a_photographed_document_is_held_out_of_the_cut_unless_pinned(tmp_path):
    plain = _nas_cut(source(tmp_path / "plain", seconds=60), "plain")
    document = plain[0]
    with_document = _photographed_document(source(tmp_path / "held", seconds=60), document)
    pinned = replace(
        _photographed_document(source(tmp_path / "pinned", seconds=60), document),
        owner_required_asset_ids=(document,),
    )

    held = _nas_cut(with_document, "held")
    kept = _nas_cut(pinned, "pinned")

    assert document in plain
    assert document not in held
    assert held, "the rest of the period still makes a film"
    assert document in kept
