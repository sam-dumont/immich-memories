"""The accepted pixel-facts-v1 recipe (its JPEG quality is deliberately 85)."""

import io
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import sqlalchemy as sa
from PIL import Image, ImageOps

from immich_memories.db import Store, now_db
from immich_memories.db.tables import pixel_facts as pixel_fact_rows
from immich_memories.db.tables import pixel_facts_thresholds
from immich_memories.store.batches import bank_rows

PRODUCER_KEY = "pixel-facts-v1"  # gitleaks:allow


def pixel_facts(preview: bytes) -> dict[str, object]:
    with Image.open(io.BytesIO(preview)) as original:
        width, height = original.size
        try:
            orientation_tag = int(original.getexif().get(274, 1) or 1)
        except Exception:  # A broken EXIF block was absent in the accepted recipe.
            orientation_tag = 1
        transposed = ImageOps.exif_transpose(original)
        needs_rotation = transposed.size != original.size or orientation_tag != 1
        if transposed is not original:
            transposed.close()
        image = original.convert("RGB")
    image.thumbnail((400, 400), Image.Resampling.LANCZOS)
    tile = io.BytesIO()
    image.save(tile, "JPEG", quality=85)
    with Image.open(io.BytesIO(tile.getvalue())) as decoded:
        luma = np.asarray(decoded.convert("L"))
    if min(luma.shape) < 3:
        raise ValueError("preview is too small for pixel-facts-v1")
    a = luma.astype(np.float32)
    laplacian = a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1]
    return {
        "sharpness": round(float(laplacian.var()), 3),
        "brightness": round(float(luma.mean()), 3),
        "contrast": round(float(luma.std()), 3),
        "dark_fraction": round(float((luma < 30).mean()), 5),
        "bright_fraction": round(float((luma > 225).mean()), 5),
        "width": width,
        "height": height,
        "orientation": "square"
        if width == height
        else "portrait"
        if height > width
        else "landscape",
        "needs_rotation": int(needs_rotation),
    }


def pixel_row(asset_id: str, preview: bytes) -> dict[str, Any]:
    """One picture's pixel facts as the store keeps them."""
    values = pixel_facts(preview)
    row = {"asset_id": asset_id, "producer_key": PRODUCER_KEY, **values, "computed_at": now_db()}
    row["needs_rotation"] = bool(row["needs_rotation"])
    return row


def remember_pixels(store: Store, rows: Sequence[Mapping[str, Any]]) -> None:
    """Bank a batch of measured pictures in one transaction."""
    latest = list({row["asset_id"]: row for row in rows}.values())
    if latest:
        bank_rows(store, pixel_fact_rows, latest, keys=("asset_id",))


def refresh_threshold(store: Store) -> None:
    with store.connect() as connection:
        sharpness: list[Any] = list(
            connection.execute(
                sa.select(pixel_fact_rows.c.sharpness).where(
                    pixel_fact_rows.c.producer_key == PRODUCER_KEY
                )
            ).scalars()
        )
    values = [v for v in sharpness if isinstance(v, (int, float)) and np.isfinite(v)]
    if values:
        row = {
            "name": "sharpness_p10",
            "value": float(np.percentile(values, 10)),
            "producer_key": PRODUCER_KEY,
            "n": len(values),
            "computed_at": now_db(),
        }
        bank_rows(store, pixel_facts_thresholds, [row], keys=("name",))
