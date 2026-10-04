"""Shared identity keeps a selected partner's episode without widening the library."""

from immich_memories.analysis.person_presence import episodes_of, present_in_episodes
from immich_memories.api.models import Asset
from immich_memories.api.person_expression import PersonExpression
from tests.household_fake import picture


def test_shared_face_retains_the_partner_episode_but_not_an_outside_owner():
    partner = [
        Asset(
            **picture(f"partner-{i}", "partner", 2, ("shared",) if i == 0 else (), minute=i),
            access_accounts=["partner"],
        )
        for i in range(4)
    ]
    outside = Asset(**picture("outside", "primary", 3, ("shared",)), access_accounts=["outside"])
    selected = present_in_episodes(
        episodes_of([*partner, outside]),
        PersonExpression("person", value="shared"),
        face_accounts={"shared": frozenset({"primary", "partner"})},
    )
    assert selected == {f"partner-{i}" for i in range(4)}
