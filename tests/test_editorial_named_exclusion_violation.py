"""A free-text request's named exclusion ("without Cy") is checked against a carrier's own
recognised faces, never its caption, which never names anyone (#2061 round 3)."""

from __future__ import annotations

from immich_memories.analysis.editorial_structure_record import _named_exclusion_violations
from immich_memories.api.models import Asset
from tests.household_fake import picture


def _asset(asset_id: str, faces: tuple[str, ...]) -> Asset:
    return Asset(**picture(asset_id, "primary", 1, faces))


def test_a_carrier_with_the_excluded_persons_face_is_a_violation():
    assets = {"cy-face": _asset("cy-face", ("cy",)), "clean": _asset("clean", ())}

    violating = _named_exclusion_violations(["cy-face", "clean"], assets, ("cy",), face_accounts={})

    assert violating == {"cy-face"}


def test_no_excluded_person_means_no_violation_regardless_of_faces():
    assets = {"cy-face": _asset("cy-face", ("cy",))}

    violating = _named_exclusion_violations(["cy-face"], assets, (), face_accounts={})

    assert violating == frozenset()
