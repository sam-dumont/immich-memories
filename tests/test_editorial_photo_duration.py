"""A requested photo duration is the length every still of the cut is held (#2131).

`generate --photo-duration 6` set `photos.duration`, but the editor held its stills for its own
fixed 3.5-4 s, so the flag changed nothing in the cut.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.config_models_render import PhotoConfig
from tests.editorial_film_fixtures import Day, film_source

MAY = (date(2030, 5, 1), date(2030, 5, 31))
PARK = (50.30, 4.65, "Park Town", "Farland")


def _still_holds(tmp_path, *, photo_seconds: float | None) -> list[float]:
    """The no-model draft, the path a NAS takes."""
    days = [Day(date(2030, 5, d), f"Day {d} in the park", PARK, moments=1) for d in (3, 9, 17, 24)]
    source = film_source(
        tmp_path, days, seconds=60, span=MAY, pictures=4, picture_gap=timedelta(minutes=9)
    )
    if photo_seconds is not None:
        photos = PhotoConfig(duration=photo_seconds)
        source = dataclasses.replace(
            source, config=source.config.model_copy(update={"photos": photos})
        )
    ports = StructurePlannerPorts(
        judge=NoModelJudge(),
        thumbnail_hash=lambda asset_id: f"{abs(hash(asset_id)):016x}"[:16],
        rules=RuleStructureReader(source),
    )
    plan = plan_structure(source, ports).plan
    return [c["seconds"] for c in plan["carriers"] if c["kind"] in ("still", "live-still")]


def test_a_requested_photo_duration_holds_every_still_that_long(tmp_path):
    holds = _still_holds(tmp_path, photo_seconds=6.0)

    assert holds
    assert min(holds) >= 5.5
    assert max(holds) <= 7.0


def test_the_default_photo_duration_keeps_the_editor_rhythm(tmp_path):
    holds = _still_holds(tmp_path, photo_seconds=None)

    assert holds
    assert min(holds) >= 3.5
    assert max(holds) <= 5.0


def test_a_full_film_holds_fewer_stills_rather_than_shave_them_back(tmp_path):
    days = [Day(date(2030, 5, d), f"Day {d} in the park", PARK, moments=2) for d in range(2, 28, 3)]
    source = film_source(
        tmp_path, days, seconds=45, span=MAY, pictures=6, picture_gap=timedelta(minutes=9)
    )
    source = dataclasses.replace(
        source, config=source.config.model_copy(update={"photos": PhotoConfig(duration=6.0)})
    )
    ports = StructurePlannerPorts(
        judge=NoModelJudge(),
        thumbnail_hash=lambda asset_id: f"{abs(hash(asset_id)):016x}"[:16],
        rules=RuleStructureReader(source),
    )
    holds = [c["seconds"] for c in plan_structure(source, ports).plan["carriers"]]

    assert len(holds) > 1
    assert min(holds) >= 5.5
