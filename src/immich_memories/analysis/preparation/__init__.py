"""The facts each picture owes, produced and banked before a film is read.

Detector heads, previews, pixel facts, motion lines, scene prints and OCR, locally or through
the inference service, resumed from the same missing-facts ledger.
"""

# The modules other packages may import; `make private-imports` holds every import to it.
__all__ = [
    "acquire",
    "demanded_previews",
    "detectors",
    "document_ocr",
    "heads",
    "motion_lines",
    "obstruction_bank",
    "pixels",
    "prepared_captions",
    "report",
    "scene_prints",
    "scope",
    "thumbnail_hashes",
]
