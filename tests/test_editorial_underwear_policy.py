"""Family viewing does not make an underwear-only portrait an automatic choice."""

import pytest

from immich_memories.analysis import editorial_shareability as share
from immich_memories.analysis.editorial_shareability_tiers import audience_check_for
from tests.test_editorial_shareability_tiers import RefusingJudge, evidence_of


@pytest.mark.parametrize("local_reader", [False, True])
def test_underwear_portrait_is_held_without_asking_a_reader(local_reader):
    evidence = evidence_of(
        heads=(("nsfw_marqo", "yes"),),
        description="A man wearing only boxer shorts stands in a room.",
    )
    check = audience_check_for("full", local_reader=local_reader)

    result = check(RefusingJudge(), evidence, "portrait")

    assert not share.allowed(result["verdict"], "family")
    assert result["finding"] == "underwear_only"


def test_an_old_family_verdict_cannot_clear_the_new_underwear_policy():
    evidence = evidence_of(description="A woman wearing only underwear poses.")

    result = share.floors_under(evidence, {"verdict": "family_only"})

    assert not share.allowed(result["verdict"], "family")
    assert result["finding"] == "underwear_only"


@pytest.mark.parametrize(
    "caption",
    [
        "A man wearing only swimming trunks stands by the pool.",
        "A baby wearing only a nappy plays on the rug.",
        "A baby wearing only a diaper sits beside a parent.",
        "A shirtless man stands in a room.",
        "Boxer shorts and a bra are displayed on a bed.",
        "A man is not wearing only underwear; he has trousers and a shirt on.",
    ],
)
def test_other_clothing_and_negated_descriptions_do_not_create_an_underwear_hold(caption):
    evidence = evidence_of(heads=(("nsfw_marqo", "yes"),), description=caption)

    result = audience_check_for("full")(RefusingJudge(), evidence, "portrait")

    assert share.allowed(result["verdict"], "family")
    assert result["finding"] != "underwear_only"


def test_the_owner_can_explicitly_clear_the_underwear_hold_for_family(tmp_path):
    from immich_memories.analysis.editorial_structure_audience import AudienceBank, AudienceGate
    from tests.test_editorial_shareability_tiers import Annotation, flag

    caption = "A man wearing only boxers stands in a room."
    gate = AudienceGate(
        RefusingJudge(),
        audience="family",
        annotations={"solo": Annotation(caption)},
        flag_rows=flag("cleared_family"),
        lines={"solo": caption},
        bank_path=tmp_path / "audit.json",
        library=AudienceBank(None, answerer="rules"),
        check_audience=audience_check_for("full"),
    )

    assert gate.verdict_of({"asset_id": "solo", "kind": "still"}) == "family_only"
    assert gate.verdicts["solo"]["finding"] == "owner_cleared"
