"""Public duration advisories from the planner's recorded outcome."""

from collections.abc import Mapping

from immich_memories.analysis.judgments.json_numbers import exact_number
from immich_memories.operational_warnings import coded


def editorial_duration_warning(realization: Mapping[str, object] | None) -> str | None:
    """Report a recorded shortfall without inferring that the library is exhausted.

    The warning is stored coded and worded where it is read (`operational_warnings`).
    """
    if not isinstance(realization, Mapping):
        return None
    status = realization.get("status")
    if status not in {"editorial_shortfall", "search_limited"}:
        return None
    values = tuple(
        realization.get(key)
        for key in ("selected_content_seconds", "content_budget_seconds", "requested_seconds")
    )
    if any((number := exact_number(value)) is None or number < 0 for value in values):
        return None
    selected, budget, requested = values
    return coded(
        "selection_stopped_early" if status == "search_limited" else "selection_short",
        selected=f"{selected:.1f}",
        requested=f"{requested:.1f}",
        budget=f"{budget:.1f}",
    )
