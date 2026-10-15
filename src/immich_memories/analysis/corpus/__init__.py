"""The admitted corpus every editorial pass reads, and what keeps a source out of it.

Name filters, re-encodes, exact and picture copies, stacks and forwarded copies are decided here,
once, before the editor sees a picture; so are capture moments, the favourite law and the trace
that records how a selection was reached.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "admission",
    "asset_merit",
    "duplicate_hashing",
    "exact_copies",
    "favourite_law",
    "forwarded_fallback",
    "generated_provenance",
    "groups",
    "moment_grouping",
    "name_filter",
    "picture_copies",
    "records",
    "trace",
    "validation",
    "visual_atlas",
]
