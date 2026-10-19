"""Per-run setup is paid once, not once per preparation round (#2686)."""

import sys
import types

import numpy as np
import pytest

from immich_memories.analysis.preparation import pixels
from immich_memories.triage import encoder as encoder_module
from immich_memories.triage.encoder import DinoEncoder
from immich_memories.triage.heads import PatchHeadBundle
from tests.annotation_rows import add_rows, annotation_store, read_rows


@pytest.fixture(autouse=True)
def _clean_caches():
    # WHY: the caches are process-wide; a test must not see another test's entries.
    encoder_module._OPENED.clear()
    yield
    encoder_module._OPENED.clear()


def _pinned_export(tmp_path, monkeypatch):
    path = tmp_path / "dinov2.onnx"
    path.write_bytes(b"pinned graph")
    import hashlib

    monkeypatch.setattr(
        encoder_module, "DINOV2_SMALL_ONNX_SHA256", hashlib.sha256(b"pinned graph").hexdigest()
    )
    return path


def test_the_encoder_is_hashed_and_opened_once_across_rounds(tmp_path, monkeypatch):
    path = _pinned_export(tmp_path, monkeypatch)
    sessions = []
    # WHY: ONNX Runtime session creation is the boundary being counted.
    monkeypatch.setattr(
        encoder_module, "_create_session", lambda *_a: sessions.append(1) or object()
    )

    first = DinoEncoder.open(path)
    second = DinoEncoder.open(path)

    assert first is second
    assert len(sessions) == 1


def test_a_changed_export_or_provider_opens_a_new_session(tmp_path, monkeypatch):
    path = _pinned_export(tmp_path, monkeypatch)
    sessions = []
    monkeypatch.setattr(
        encoder_module, "_create_session", lambda *_a: sessions.append(1) or object()
    )

    DinoEncoder.open(path)
    DinoEncoder.open(path, provider="cpu")

    assert len(sessions) == 2


def test_onnx_threads_follow_the_cpu_limit_the_process_has(tmp_path, monkeypatch):
    seen = {}

    class Options:
        pass

    fake_ort = types.SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        SessionOptions=Options,
        GraphOptimizationLevel=types.SimpleNamespace(ORT_ENABLE_ALL=1),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    # WHY: the cgroup limit and the ONNX session are the two boundaries.
    monkeypatch.setattr("immich_memories.onnx_session.available_cpus", lambda: 3)
    monkeypatch.setattr(
        encoder_module,
        "open_inference_session",
        lambda _ort, _path, *, options, providers: (
            providers,
            seen.update(threads=options.intra_op_num_threads),
        ),
    )

    encoder_module._create_session(tmp_path / "m.onnx", "cpu")

    assert seen["threads"] == 2


def test_head_bundles_load_from_disk_once_per_file(tmp_path, monkeypatch):
    path = tmp_path / "patch.npz"
    PatchHeadBundle(
        encoder_key="k",
        name="n",
        version="1",
        mu=np.zeros(384, dtype=np.float32),
        sd=np.ones(384, dtype=np.float32),
        w=np.zeros(384, dtype=np.float32),
        b=0.0,
    ).save(path)

    assert PatchHeadBundle.load(path) is PatchHeadBundle.load(path)


def _pixel_row(asset_id, sharpness):
    return {
        "asset_id": asset_id,
        "producer_key": pixels.PRODUCER_KEY,
        "sharpness": sharpness,
        "needs_rotation": False,
    }


def _threshold(store):
    return read_rows(store, "pixel_facts_thresholds")[0]


def test_the_sharpness_threshold_is_not_recomputed_while_the_library_is_stable():
    store = annotation_store()
    add_rows(store, "pixel_facts", *(_pixel_row(f"a{i}", float(i)) for i in range(100)))
    pixels.refresh_threshold(store)
    banked = _threshold(store)

    # One more picture in a hundred is under the 5 % that moves a 10th percentile.
    add_rows(store, "pixel_facts", _pixel_row("late", 1000.0))
    pixels.refresh_threshold(store)

    assert _threshold(store) == banked


def test_the_sharpness_threshold_follows_a_library_that_grew_materially():
    store = annotation_store()
    add_rows(store, "pixel_facts", *(_pixel_row(f"a{i}", float(i)) for i in range(100)))
    pixels.refresh_threshold(store)
    before = _threshold(store)

    add_rows(store, "pixel_facts", *(_pixel_row(f"b{i}", 500.0 + i) for i in range(50)))
    pixels.refresh_threshold(store)

    after = _threshold(store)
    assert after["n"] == 150 and after["value"] != before["value"]


def test_every_round_reuses_one_connection_pool_per_service():
    from immich_memories.analysis.preparation.remote_facts import (
        RemoteFactsClient,
        close_shared_clients,
    )
    from immich_memories.config.models.inference import InferenceConfig

    config = InferenceConfig(facts_base_url="http://inference.test:8092")
    try:
        with RemoteFactsClient(config) as first:
            pool = first._client
        with RemoteFactsClient(config) as second:
            assert second._client is pool and not pool.is_closed
        other = InferenceConfig(facts_base_url="http://elsewhere.test:8092")
        with RemoteFactsClient(other) as third:
            assert third._client is not pool
    finally:
        close_shared_clients()


def test_a_round_adds_its_facts_to_the_live_views_instead_of_copying_the_period():
    from immich_memories.analysis.runtime.film_preparation import _merged

    live = {f"a{n}": n for n in range(5)}

    assert _merged(live, {"b": 1}) is live
    assert live["b"] == 1
    frozen = {"a": 1}
    merged = _merged(types.MappingProxyType(frozen), {"b": 2})
    assert merged == {"a": 1, "b": 2} and frozen == {"a": 1}


def test_the_line_reader_is_built_once_per_prepared_period(monkeypatch):
    from immich_memories.analysis.runtime.evidence import AnnotationReadings

    built = []
    readings = AnnotationReadings(store=None, config=None, people={})  # type: ignore[arg-type]
    # WHY: building the reader walks the whole period; counting builds is the point.
    monkeypatch.setattr(
        AnnotationReadings,
        "_new_reader",
        lambda _self, prepared: built.append(prepared) or object(),
    )
    period, other = object(), object()

    assert readings.reader(period) is readings.reader(period)
    readings.reader(other)

    assert built == [period, other]
