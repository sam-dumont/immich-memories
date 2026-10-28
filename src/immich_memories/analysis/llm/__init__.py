"""The model transport every reader asks through.

Providers and the two request dialects, one connection per prompt, batches, the single-flight
lock on a paid answer, and the run's spend counters. Nothing here knows what a film is.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "async_bridge",
    "batch",
    "failures",
    "genai_trace",
    "metrics",
    "provider_failure",
    "provider_health",
    "provider_status",
    "providers",
    "query",
    "single_flight",
    "text_identity",
    "usage_record",
    "wire",
]
