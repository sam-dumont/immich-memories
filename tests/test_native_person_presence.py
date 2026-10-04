"""Shared identity keeps a selected partner's picture without widening the library."""

from immich_memories.analysis.person_presence import present_on_assets
from immich_memories.api.models import Asset
from immich_memories.api.person_expression import PersonExpression
from tests.household_fake import picture


def test_shared_face_holds_on_the_partner_picture_but_not_an_outside_owner():
    partner = [
        Asset(
            **picture(f"partner-{i}", "partner", 2, ("shared",) if i == 0 else (), minute=i),
            access_accounts=["partner"],
        )
        for i in range(4)
    ]
    outside = Asset(**picture("outside", "primary", 3, ("shared",)), access_accounts=["outside"])
    selected = present_on_assets(
        [*partner, outside],
        PersonExpression("person", value="shared"),
        face_accounts={"shared": frozenset({"primary", "partner"})},
    )
    # Strict per picture: the partner frames without the face stay out.
    assert selected == {"partner-0"}
