"""Synthetic text-only audience evidence; no personal photographs are involved."""

from functools import partial

from immich_memories.analysis.annotation_lines import AssetAnnotationLine
from immich_memories.analysis.editorial_shareability import check_audience, evidence_for_unit
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import scratch_judge
from immich_memories.conformance.runtime import Case


def audience(llm: LLMConfig, *, exposure: bool) -> str:
    description = (
        "A person wearing a coat and trousers at the seaside."
        if exposure
        else "An adult using a toilet."
    )
    annotation = AssetAnnotationLine(
        "synthetic", description, description, heads=(("nsfw_marqo", "yes"),) if exposure else ()
    )
    evidence = evidence_for_unit(
        {"asset_id": "synthetic", "members": ["synthetic"]}, {"synthetic": annotation}, {}, {}
    )
    with scratch_judge(llm) as judge:
        answer = check_audience(judge, evidence, "conformance")
    assert answer["parsed"], "audience answer could not be parsed"
    if exposure:
        assert answer["exposure"] and answer["exposure"]["parsed"], (
            "exposure review was skipped or invalid"
        )
        assert answer["exposure"]["clearances"] == [
            {"member": "p1", "basis": "clothed_or_covered"}
        ], "review did not identify the stated clothing"
        assert answer["verdict"] == "family_only", (
            "text review incorrectly lifted the detector hold"
        )
        return "recognizes stated clothing while retaining the detector hold"
    assert answer["verdict"] == "do_not_show", "private toileting activity was not withheld"
    return "private toileting activity stays out of exports"


def audience_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "audience activity",
            partial(audience, llm, exposure=False),
            frozenset({"analysis.editorial_shareability:_read_audience"}),
        ),
        Case(
            "audience exposure",
            partial(audience, llm, exposure=True),
            frozenset({"analysis.editorial_shareability:_review_exposure"}),
        ),
    )
