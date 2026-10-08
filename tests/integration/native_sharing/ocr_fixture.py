"""Stored text boxes exercise the REST contract used by every Immich OCR model."""

from __future__ import annotations

import subprocess
from uuid import UUID

OCR_TEXT = "PASSPORT / PASSEPORT\nPassport No: EXAMPLE123\nTexte multilingue: été"


def seed_ocr(database_container: str | None, asset_id: str) -> None:
    """Add normalized, multilingual OCR boxes only to the disposable gate database."""
    if not database_container or not database_container.startswith("immich-gate-"):
        raise ValueError("OCR fixture needs its disposable immich-gate database container")
    # PP-OCRv6 changes recognition, not the stored text-box contract. Insert out of
    # reading order so the real REST read also proves our box ordering.
    sql = """INSERT INTO asset_ocr
("assetId", x1, y1, x2, y2, x3, y3, x4, y4, "boxScore", "textScore", text)
VALUES
(:'asset', 0.1, 0.6, 0.9, 0.6, 0.9, 0.7, 0.1, 0.7, 0.99, 0.99, 'Texte multilingue: été'),
(:'asset', 0.1, 0.1, 0.9, 0.1, 0.9, 0.2, 0.1, 0.2, 0.99, 0.99, 'PASSPORT / PASSEPORT'),
(:'asset', 0.1, 0.3, 0.9, 0.3, 0.9, 0.4, 0.1, 0.4, 0.99, 0.99, 'Passport No: EXAMPLE123');
"""
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            database_container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "immich",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"asset={UUID(asset_id)}",
        ],
        input=sql,
        text=True,
        check=True,
        capture_output=True,
    )
