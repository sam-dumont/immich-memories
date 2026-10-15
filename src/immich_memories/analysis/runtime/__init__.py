"""Composition: from `SmartPipeline` to the planner, with the production ports wired in.

The entry point for a run is `smart_pipeline.SmartPipeline`; `composition.build_smart_pipeline`
builds it for the editorial route.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "composition",
    "duration_advisory",
    "evidence",
    "left_out",
    "orchestration",
    "period_accounts",
    "plan",
    "ports",
    "smart_pipeline",
]
