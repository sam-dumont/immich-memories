"""Bounded text judgments over the transport: what a stage asks and how its answer is read.

A text request and its judgment key, the gateway that banks answers, strict JSON envelopes,
page bounds and recovery when an answer comes back incomplete.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "json_completion",
    "json_envelopes",
    "json_numbers",
    "page_recovery",
    "prompt_pages",
    "reader_concurrency",
    "strict_json",
    "text_artifacts",
    "text_failures",
    "text_gateway",
    "text_judge",
    "text_request",
]
