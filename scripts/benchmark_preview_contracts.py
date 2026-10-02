"""Compare shipped still-producer contracts on generated EXIF and malformed inputs."""

import hashlib
import io
import json

import cv2
import numpy as np
from PIL import Image

from immich_memories.analysis.duplicate_hashing import compute_thumbnail_hash
from immich_memories.analysis.editorial_preparation_pixels import pixel_facts
from immich_memories.triage.preprocess import preprocess_image_bytes


def main():
    image = Image.new("RGB", (40, 24), "navy")
    image.paste((255, 200, 0), (0, 0, 13, 9))
    image.paste((20, 200, 80), (26, 12, 40, 24))
    for orientation in (1, 6, 8):
        exif = Image.Exif()
        exif[274] = orientation
        stream = io.BytesIO()
        image.save(stream, "JPEG", quality=95, exif=exif)
        payload = stream.getvalue()
        with Image.open(io.BytesIO(payload)) as raw:
            pillow = np.asarray(raw.convert("RGB"))
        opencv = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB
        )
        facts = pixel_facts(payload)
        print(
            json.dumps(
                {
                    "orientation": orientation,
                    "pillow_shape": pillow.shape,
                    "opencv_shape": opencv.shape,
                    "pixels_equal": np.array_equal(pillow, opencv),
                    "needs_rotation": facts["needs_rotation"],
                    "thumbnail_hash": compute_thumbnail_hash(payload),
                    "tensor_sha256": hashlib.sha256(
                        preprocess_image_bytes(payload).tobytes()
                    ).hexdigest(),
                }
            )
        )
    for name, producer in [
        ("thumbnail", compute_thumbnail_hash),
        ("pixels", pixel_facts),
        ("dino", preprocess_image_bytes),
    ]:
        try:
            result = producer(b"not a JPEG")
            print(json.dumps({"producer": name, "malformed_result": result}))
        except Exception as exc:
            print(json.dumps({"producer": name, "malformed_error": type(exc).__name__}))


if __name__ == "__main__":
    main()
