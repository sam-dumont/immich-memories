"""A frame's scene print is read once from its preview and banked, like its hash."""

import io
import weakref

import numpy as np
from PIL import Image

from immich_memories.analysis.preparation.scene_prints import CachedScenePrints


def _jpeg(colour) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


PREVIEWS = {"red": _jpeg((200, 0, 0)), "blue": _jpeg((0, 0, 200))}


class _Encoder:
    """Stands in for the pinned DINOv2 export: a pack from each image's mean colour."""

    key = "test-encoder"

    def __init__(self) -> None:
        self.images = 0

    def embed(self, batch: np.ndarray) -> np.ndarray:
        self.images += len(batch)
        return batch.mean(axis=(2, 3))


def _prints(tmp_path, encoder):
    opened = []

    def open_encoder():
        opened.append(True)
        return encoder

    prints = CachedScenePrints(
        tmp_path / "scene-prints.sqlite", PREVIEWS.get, open_encoder=open_encoder
    )
    return prints, opened


def test_a_preview_is_encoded_once_and_read_from_the_bank_after(tmp_path):
    encoder = _Encoder()
    prints, _ = _prints(tmp_path, encoder)
    first = prints("red")
    prints.close()

    again, opened = _prints(tmp_path, encoder)
    second = again("red")

    assert encoder.images == 1
    assert opened == []
    np.testing.assert_allclose(first, second, atol=1e-3)


def test_different_scenes_give_different_prints(tmp_path):
    prints, _ = _prints(tmp_path, _Encoder())

    red, blue = prints("red"), prints("blue")

    assert not np.allclose(red, blue)


def test_a_frame_with_no_preview_has_no_print(tmp_path):
    prints, opened = _prints(tmp_path, _Encoder())

    assert prints("missing") is None
    assert opened == []


def test_an_install_without_the_encoder_reads_no_scene(tmp_path):
    prints = CachedScenePrints(
        tmp_path / "scene-prints.sqlite", PREVIEWS.get, open_encoder=lambda: None
    )

    assert prints("red") is None


def test_close_releases_the_owned_encoder_and_can_reopen(tmp_path):
    references = []

    def open_encoder():
        encoder = _Encoder()
        references.append(weakref.ref(encoder))
        return encoder

    prints = CachedScenePrints(
        tmp_path / "scene-prints.sqlite", PREVIEWS.get, open_encoder=open_encoder
    )
    prints("red")
    assert references[0]() is not None

    prints.close()
    assert references[0]() is None, "closing must release the encoder's native session"
    prints.close()
    prints("blue")
    assert len(references) == 2
    assert references[1]() is not None
    prints.close()
    assert references[1]() is None


class _PinnedStandIn:
    """# WHY: the pinned 88 MB export is not in the test environment; what matters is that
    the heads pass and the print reader agree on the key and the pack."""

    def __init__(self) -> None:
        from immich_memories.analysis.preparation.scene_prints import PRINT_ENCODER_KEY

        self.key = PRINT_ENCODER_KEY
        self.images = 0

    def embed(self, batch: np.ndarray) -> np.ndarray:
        self.images += len(batch)
        return np.repeat(batch.mean(axis=(2, 3)), 6 * 128, axis=1)

    def embed_with_patches(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.embed(batch), np.zeros((len(batch), 256, 384), np.float32)


def test_the_heads_pass_banks_the_print_selection_reads_without_encoding_again(tmp_path):
    from immich_memories.analysis.preparation.heads import PUBLIC_HEAD_VERSIONS, prepare_heads
    from tests.annotation_rows import annotation_store
    from tests.test_editorial_preparation_heads import bundle_at

    heads_encoder, print_encoder = _PinnedStandIn(), _PinnedStandIn()
    encoder_path = tmp_path / "encoder.onnx"
    encoder_path.write_bytes(b"")
    bank = tmp_path / "scene-prints.sqlite"
    prepare_heads(
        asset_ids=["red", "blue"],
        store=annotation_store(),
        bundle_path=bundle_at(
            tmp_path / "heads.npz", PUBLIC_HEAD_VERSIONS, encoder_key=heads_encoder.key
        ),
        encoder_path=encoder_path,
        head_versions=PUBLIC_HEAD_VERSIONS,
        preview_for=PREVIEWS.__getitem__,
        batch_size=8,
        check_cancelled=lambda: None,
        progress=lambda *_args: None,
        scene_prints=bank,
        open_encoder=lambda _path, **_kwargs: heads_encoder,
    )

    prints = CachedScenePrints(bank, PREVIEWS.get, open_encoder=lambda: print_encoder)
    red = prints("red")

    assert print_encoder.images == 0
    assert heads_encoder.images == 2
    from immich_memories.triage.preprocess import preprocess_image_bytes

    expected = print_encoder.embed(preprocess_image_bytes(PREVIEWS["red"])[np.newaxis])[0]
    np.testing.assert_array_equal(red, expected.astype(np.float16).astype(np.float32))
