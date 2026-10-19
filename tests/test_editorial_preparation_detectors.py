"""Detector portability, refusal reporting and cancellation, on synthetic probabilities."""

import io
import json
import logging
import os
import signal
import sys
import threading
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from immich_memories.analysis.preparation import detector_workers, detectors
from immich_memories.operations.cancellation import PipelineCancelled
from tests.annotation_rows import annotation_store


class FakeDocling:
    head = "doc_docling"
    version = detectors.DOCLING_VERSION
    encoder_key = detectors.DOCLING_REPO
    classes = ("photograph", "signature")

    def __init__(self, **_):
        pass

    def batch(self, images):
        return np.array([[0.8, 0.2] for _ in images])


def _job(tmp_path, pending):
    path = tmp_path / "preview.jpg"
    Image.new("RGB", (80, 60), "white").save(path)
    facts_path = tmp_path / "facts.jsonl"
    return facts_path, {
        "facts_path": str(facts_path),
        "pending": pending,
        "previews": {"a": str(path)},
        "batch_size": 16,
        "allow_downloads": False,
        "cache_dir": None,
        "marqo_onnx": str(tmp_path / "absent-nsfw-marqo-384.onnx"),
    }


def _banked_facts(facts_path):
    if not facts_path.is_file():
        return []
    return [json.loads(line) for line in facts_path.read_text().splitlines()]


def test_one_missing_detector_preserves_other_completed_facts(monkeypatch, tmp_path):
    facts_path, job = _job(tmp_path, {"nsfw_marqo": ["a"], "doc_docling": ["a"]})
    # WHY: the real Docling seat downloads a pinned snapshot from Hugging Face.
    monkeypatch.setattr(detectors, "Docling", FakeDocling)

    errors = detectors._worker(job)

    assert "doc_docling" not in errors
    assert [
        (row["head"], row["version"], row["label"], row["confidence"], row["encoder_key"])
        for row in _banked_facts(facts_path)
    ] == [
        ("doc_docling", "det-v2", "photograph", 0.8, detectors.DOCLING_REPO),
    ]


def test_the_torch_free_transform_produces_the_tensor_the_export_expects():
    """The numpy transform is what lets this seat drop timm and torchvision.

    Short side to 384, centre crop, and 0.5/0.5 normalisation -- the data config
    the pinned checkpoint carries. `export_marqo_onnx.py --verify-pixels` proves
    it against timm's own pipeline; this keeps its shape and range honest.
    """
    wide = Image.new("RGB", (1000, 500), "white")
    tall = Image.new("RGB", (500, 1000), "black")

    pixels = detectors.marqo_pixels([wide, tall])

    assert pixels.shape == (2, 3, detectors.MARQO_SIDE, detectors.MARQO_SIDE)
    assert pixels.dtype == np.float32
    assert pixels[0].min() == pytest.approx(1.0) and pixels[0].max() == pytest.approx(1.0)
    assert pixels[1].min() == pytest.approx(-1.0) and pixels[1].max() == pytest.approx(-1.0)


def test_the_document_detector_without_its_snapshot_names_the_repository(monkeypatch):
    class ColdCache(ModuleType):
        @staticmethod
        def hf_hub_download(*_args, **_kwargs):
            raise OSError("offline and not in the local cache")

    # WHY: hf_hub_download is the Hugging Face boundary; huggingface-hub itself
    # is an `editorial`-extra dependency the unit environment does not install.
    monkeypatch.setitem(sys.modules, "huggingface_hub", ColdCache("huggingface_hub"))

    with pytest.raises(detectors.DetectorModelUnavailable) as raised:
        detectors.Docling(allow_downloads=False, cache_dir="/configured/cache")

    assert detectors.DOCLING_REPO in str(raised.value)
    assert "/configured/cache" in str(raised.value)
    assert "models fetch" in str(raised.value)


def test_a_producer_without_its_model_names_the_model_and_the_fix(tmp_path):
    _facts_path, job = _job(tmp_path, {"nsfw_marqo": ["a"]})

    reason = detectors._worker(job)["nsfw_marqo"]

    assert detectors.MARQO_ONNX_ID in reason
    assert "absent-nsfw-marqo-384.onnx" in reason
    assert "models fetch" in reason


def test_a_graph_that_is_not_the_pinned_export_is_refused_by_digest(tmp_path):
    _facts_path, job = _job(tmp_path, {"nsfw_marqo": ["a"]})
    present = tmp_path / "nsfw-marqo-384.onnx"
    present.write_bytes(b"not the pinned graph")
    job["marqo_onnx"] = str(present)

    reason = detectors._worker(job)["nsfw_marqo"]

    assert detectors.MARQO_ONNX_SHA256[:12] in reason
    assert "models fetch --force" in reason


def test_a_refusal_is_published_before_the_other_producer_runs(monkeypatch, tmp_path):
    """The worker loads every producer first, so its refusal is readable at once."""
    facts_path, job = _job(tmp_path, {"nsfw_marqo": ["a"], "doc_docling": ["a"]})
    progress_path = tmp_path / "progress.json"
    job["progress_path"] = str(progress_path)
    published = []

    class WatchingDocling(FakeDocling):
        def batch(self, images):
            published.append(progress_path.read_text())
            return super().batch(images)

    # WHY: the real Docling seat downloads a pinned snapshot from Hugging Face.
    monkeypatch.setattr(detectors, "Docling", WatchingDocling)

    detectors._worker(job)

    assert published, "the surviving producer never ran"
    assert detectors.MARQO_ONNX_ID in published[0]
    assert len(_banked_facts(facts_path)) == 1


def test_the_parent_logs_each_refusal_once_while_the_worker_is_still_running(tmp_path, caplog):
    progress_path = tmp_path / "progress.json"
    progress = detectors._WorkerProgress(str(progress_path), total=2)
    progress.refuse("nsfw_marqo", "nsfw_marqo has no model: run models fetch")
    progress.record(1)
    watch = detectors._WorkerWatch(progress_path, lambda *_: None, lambda: None)

    with caplog.at_level(logging.WARNING):
        watch.poll()
        watch.poll()

    assert [record.getMessage() for record in caplog.records] == [
        "nsfw_marqo has no model: run models fetch"
    ]


def test_cancellation_terminates_detector_process_group(monkeypatch, tmp_path):
    killed = []
    captured = []

    class Process:
        pid = 12345
        returncode = None
        stdin = io.StringIO()

        def poll(self):
            return None

        def wait(self, **_):
            return 0

    def popen(argv, **kwargs):
        captured.append((argv, kwargs))
        return Process()

    checks = []

    def check():
        checks.append(True)
        if len(checks) == 2:
            raise PipelineCancelled()

    # The store is opened before the subprocess boundary is replaced: opening it
    # checks the mount table through subprocess.run, which the same module-level
    # patch would otherwise catch too.
    store = annotation_store()
    monkeypatch.setattr(detector_workers, "_IDLE", {})
    # WHY: both replace the detector subprocess boundary itself.
    monkeypatch.setattr(detector_workers.subprocess, "Popen", popen)
    monkeypatch.setattr(detector_workers.os, "killpg", lambda *args: killed.append(args))
    with pytest.raises(PipelineCancelled):
        detectors.prepare_detectors(
            pending={"nsfw_marqo": ["a"]},
            store=store,
            preview_paths={"a": tmp_path / "preview"},
            python="/configured/python",
            cache_dir="/configured/cache",
            marqo_onnx=tmp_path / "nsfw-marqo-384.onnx",
            allow_downloads=False,
            batch_size=16,
            check_cancelled=check,
            progress=lambda *_: None,
        )
    assert killed == [(12345, signal.SIGTERM)]
    assert captured[0][0][0] == "/configured/python"
    assert captured[0][0][1].endswith("analysis/preparation/detectors.py")
    assert captured[0][1]["env"]["HF_HUB_OFFLINE"] == "1"
    assert captured[0][1]["env"]["HF_HUB_CACHE"] == "/configured/cache"


class FakeSession:
    """An ORT session that remembers what it was opened with."""

    def __init__(self, model_path, options, providers, running=None):
        self.model_path = model_path
        self.options = options
        self.providers = list(providers)
        self._running = list(providers if running is None else running)

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def get_providers(self):
        return list(self._running)

    def run(self, _outputs, _feed):
        return [np.zeros((1, len(detectors.DOCLING_LABELS)), dtype=np.float32)]


class FakeSessionOptions:
    """ONNX Runtime's session options, down to the settings the worker makes."""

    def __init__(self):
        self.intra_op_num_threads = 0
        self.graph_optimization_level = None
        self.entries: dict[str, str] = {}

    def add_session_config_entry(self, key, value):
        self.entries[key] = value


def _fake_onnxruntime(monkeypatch, available, opened, *, refuse=(), running=None):
    """# WHY: ONNX Runtime is the boundary under test -- which execution providers
    a session is opened with, and what it answers when one turns the graph down.
    No CUDA host exists on Apple Silicon, so the runtime is what has to be stood in for."""

    def session(path, sess_options, providers):
        opened.append(list(providers))
        if providers[0] in refuse:
            raise RuntimeError(f"{providers[0]} could not be initialised")
        return FakeSession(path, sess_options, providers, running)

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            get_available_providers=lambda: list(available),
            SessionOptions=FakeSessionOptions,
            GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_EXTENDED="extended"),
            disable_telemetry_events=lambda: None,
            InferenceSession=session,
        ),
    )


def _fake_snapshot(monkeypatch, tmp_path):
    """# WHY: hf_hub_download is the Hugging Face boundary; the pinned Docling
    snapshot is 16.8 MB and this test never reads a byte of it."""
    model = tmp_path / "model.onnx"
    model.write_bytes(b"not read: the session is stood in for too")
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(hf_hub_download=lambda *_args, **_kwargs: str(model)),
    )


@pytest.mark.parametrize(
    ("choice", "available", "expected"),
    [
        (
            "auto",
            ("CUDAExecutionProvider", "CPUExecutionProvider"),
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ),
        ("auto", ("CPUExecutionProvider",), ["CPUExecutionProvider"]),
        (
            "cuda",
            ("CUDAExecutionProvider", "CPUExecutionProvider"),
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ),
        ("cpu", ("CUDAExecutionProvider", "CPUExecutionProvider"), ["CPUExecutionProvider"]),
    ],
)
def test_a_detector_session_is_opened_on_the_provider_the_deployment_chose(
    monkeypatch, tmp_path, choice, available, expected
):
    opened: list[list[str]] = []
    _fake_onnxruntime(monkeypatch, available, opened)
    _fake_snapshot(monkeypatch, tmp_path)

    detectors.Docling(allow_downloads=False, cache_dir=None, provider=choice)

    assert opened == [expected]


def test_naming_a_provider_the_runtime_was_not_built_with_is_refused(monkeypatch, tmp_path):
    _fake_onnxruntime(monkeypatch, ("CPUExecutionProvider",), [])
    _fake_snapshot(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="CUDAExecutionProvider is unavailable"):
        detectors.Docling(allow_downloads=False, cache_dir=None, provider="cuda")


def test_a_card_that_refuses_the_graph_is_said_once_and_the_cpu_decides(
    monkeypatch, tmp_path, caplog
):
    opened: list[list[str]] = []
    monkeypatch.setattr(detectors, "_ANNOUNCED", set())
    _fake_onnxruntime(
        monkeypatch,
        ("CUDAExecutionProvider", "CPUExecutionProvider"),
        opened,
        refuse=("CUDAExecutionProvider",),
    )
    _fake_snapshot(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING, logger=detectors.__name__):
        detectors.Docling(allow_downloads=False, cache_dir=None, provider="cuda")
        detectors.Docling(allow_downloads=False, cache_dir=None, provider="cuda")

    assert opened[0] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert opened[1] == ["CPUExecutionProvider"]
    said = [record.getMessage() for record in caplog.records]
    assert len(said) == 1, said
    assert "doc_docling" in said[0]
    assert "deciding on CPUExecutionProvider" in said[0]


def test_a_session_the_card_never_joined_names_what_is_running(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(detectors, "_ANNOUNCED", set())
    _fake_onnxruntime(
        monkeypatch,
        ("CUDAExecutionProvider", "CPUExecutionProvider"),
        [],
        running=["CPUExecutionProvider"],
    )
    _fake_snapshot(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING, logger=detectors.__name__):
        detectors.Docling(allow_downloads=False, cache_dir=None, provider="cuda")

    assert [record.getMessage() for record in caplog.records] == [
        "doc_docling: asked for CUDAExecutionProvider, running on CPUExecutionProvider"
    ]


def test_the_in_process_worker_takes_the_card_where_there_is_one(monkeypatch, tmp_path):
    """No knob: the worker runs on whatever the host it was configured for has."""
    opened: list[list[str]] = []
    _fake_onnxruntime(monkeypatch, ("CUDAExecutionProvider", "CPUExecutionProvider"), opened)
    _fake_snapshot(monkeypatch, tmp_path)
    _facts_path, job = _job(tmp_path, {"doc_docling": ["a"]})

    detectors._open_detector("doc_docling", job)

    assert opened == [["CUDAExecutionProvider", "CPUExecutionProvider"]]


class FakeMarqo:
    """Answers per image so a clip's frames can disagree the way real ones do."""

    head = detectors.MARQO_HEAD
    version = detectors.MARQO_VERSION
    encoder_key = detectors.MARQO_ONNX_ID
    classes = detectors.MARQO_CLASSES

    def __init__(self, scores, **_):
        self._scores = scores

    def batch(self, images):
        return np.array(
            [[self._scores[image.size[0]], 1 - self._scores[image.size[0]]] for image in images]
        )


def _frames(tmp_path, widths):
    """One JPEG per frame, each a different width so the fake head can tell them apart."""
    paths = []
    for width in widths:
        path = tmp_path / f"frame-{width}.jpg"
        Image.new("RGB", (width, 60), "white").save(path)
        paths.append(str(path))
    return paths


def test_a_clip_is_held_when_any_one_of_its_eight_frames_is(monkeypatch, tmp_path):
    """A hold anywhere in a clip holds the clip: the head keeps the strongest frame."""
    facts_path, job = _job(tmp_path, {detectors.MARQO_HEAD: ["a"]})
    widths = [80 + step for step in range(1, 9)]
    job["frames"] = {"a": _frames(tmp_path, widths)}
    scores = dict.fromkeys([*widths, 80], 0.02)
    scores[widths[6]] = 0.93
    # WHY: the real seat loads a 384px ONNX export from a digest-pinned file on disk.
    monkeypatch.setattr(detectors, "Marqo", lambda **_: FakeMarqo(scores))

    assert detectors._worker(job) == {}

    assert [(row["label"], row["confidence"]) for row in _banked_facts(facts_path)] == [
        ("yes", 0.93)
    ]


def test_a_still_keeps_its_one_preview_read(monkeypatch, tmp_path):
    facts_path, job = _job(tmp_path, {detectors.MARQO_HEAD: ["a"]})
    # WHY: the real seat loads a 384px ONNX export from a digest-pinned file on disk.
    monkeypatch.setattr(detectors, "Marqo", lambda **_: FakeMarqo({80: 0.04}))

    assert detectors._worker(job) == {}

    assert [(row["label"], row["confidence"]) for row in _banked_facts(facts_path)] == [
        ("no", 0.04)
    ]


def test_a_clip_the_preview_alone_holds_stays_held(monkeypatch, tmp_path):
    """Immich renders the preview rather than serving a keyframe, so the sampler never
    sees it. A version that reads more frames must never hold fewer clips."""
    facts_path, job = _job(tmp_path, {detectors.MARQO_HEAD: ["a"]})
    widths = [80 + step for step in range(1, 9)]
    job["frames"] = {"a": _frames(tmp_path, widths)}
    scores = dict.fromkeys(widths, 0.02) | {80: 0.61}
    # WHY: the real seat loads a 384px ONNX export from a digest-pinned file on disk.
    monkeypatch.setattr(detectors, "Marqo", lambda **_: FakeMarqo(scores))

    assert detectors._worker(job) == {}

    assert [(row["label"], row["confidence"]) for row in _banked_facts(facts_path)] == [
        ("yes", 0.61)
    ]


def test_a_worker_session_sizes_its_pool_from_the_job_and_sleeps_when_idle(monkeypatch, tmp_path):
    """The parent knows the CPUs the process may use; the worker's sessions follow it."""
    captured = []

    def session(path, sess_options, providers):
        captured.append(sess_options)
        return FakeSession(path, sess_options, providers)

    _fake_onnxruntime(monkeypatch, ("CPUExecutionProvider",), [])
    monkeypatch.setattr(sys.modules["onnxruntime"], "InferenceSession", session)
    _fake_snapshot(monkeypatch, tmp_path)
    _facts_path, job = _job(tmp_path, {"doc_docling": ["a"]})
    job["threads"] = 3

    detectors._open_detector("doc_docling", job)

    (options,) = captured
    assert options.intra_op_num_threads == 3
    assert options.entries == {
        "session.intra_op.allow_spinning": "0",
        "session.inter_op.allow_spinning": "0",
    }


class InProcessWorker:
    """The detector worker's job loop on a thread, fed through a pipe like the real child.

    It runs this module's own loop, so a stand-in producer patched here reaches it.
    """

    spawned: list[list[str]] = []

    def __init__(self, argv, **kwargs):
        InProcessWorker.spawned.append(argv)
        self.env = kwargs["env"]
        self.pid = 4242
        read_end, write_end = os.pipe()
        self.stdin = os.fdopen(write_end, "w")
        self._jobs = os.fdopen(read_end, "r")
        self._thread = threading.Thread(
            target=detectors._serve, args=(self._jobs, 30.0), daemon=True
        )
        self._thread.start()

    def poll(self):
        return None if self._thread.is_alive() else 0

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return 0


@pytest.fixture
def worker_pool(monkeypatch):
    """A pool of in-process workers this test owns, retired when it ends."""
    InProcessWorker.spawned = []
    monkeypatch.setattr(detector_workers, "_IDLE", {})
    # WHY: the detector subprocess is the boundary; its job loop runs here on a thread.
    monkeypatch.setattr(detector_workers.subprocess, "Popen", InProcessWorker)
    yield InProcessWorker.spawned
    detector_workers.retire_detector_workers()


def _previews(tmp_path, ids):
    paths = {}
    for asset_id in ids:
        path = tmp_path / f"{asset_id}.jpg"
        Image.new("RGB", (80, 60), "white").save(path)
        paths[asset_id] = path
    return paths


def test_one_worker_decides_every_batch_of_a_preparation(monkeypatch, tmp_path, worker_pool):
    """Each batch used to start a fresh interpreter, import ONNX Runtime and load its models."""
    from immich_memories.store.editorial_preparation import heads_missing_for

    opened = []

    class CountingDocling(FakeDocling):
        def __init__(self, **kwargs):
            opened.append(kwargs)

    # WHY: the real Docling seat downloads a pinned snapshot from Hugging Face.
    monkeypatch.setattr(detectors, "Docling", CountingDocling)
    store = annotation_store()
    batches = [["a1", "a2"], ["b1"], ["c1", "c2", "c3"]]

    results = [
        detectors.prepare_detectors(
            pending={"doc_docling": batch},
            store=store,
            preview_paths=_previews(tmp_path, batch),
            python=sys.executable,
            cache_dir="",
            marqo_onnx=tmp_path / "nsfw-marqo-384.onnx",
            allow_downloads=False,
            batch_size=16,
            check_cancelled=lambda: None,
            progress=lambda *_: None,
        )
        for batch in batches
    ]

    assert results == [{}, {}, {}]
    assert len(worker_pool) == 1
    assert len(opened) == 1
    every = [asset_id for batch in batches for asset_id in batch]
    assert heads_missing_for(store, every, "doc_docling", detectors.DOCLING_VERSION) == ()


def test_the_worker_is_told_the_cpus_the_process_may_use(monkeypatch, tmp_path, worker_pool):
    from immich_memories import onnx_session

    # WHY: the CPU count is the host boundary (affinity and cgroup quota).
    monkeypatch.setattr(onnx_session, "available_cpus", lambda: 4)
    # WHY: the real Docling seat downloads a pinned snapshot from Hugging Face.
    monkeypatch.setattr(detectors, "Docling", FakeDocling)

    detectors.prepare_detectors(
        pending={"doc_docling": ["a"]},
        store=annotation_store(),
        preview_paths=_previews(tmp_path, ["a"]),
        python=sys.executable,
        cache_dir="",
        marqo_onnx=tmp_path / "nsfw-marqo-384.onnx",
        allow_downloads=False,
        batch_size=16,
        check_cancelled=lambda: None,
        progress=lambda *_: None,
    )

    assert detector_workers._IDLE, "the worker was not kept for the next batch"
    (worker,) = detector_workers._IDLE.values()
    assert worker.process.env["OMP_NUM_THREADS"] == "3"


def test_the_real_worker_answers_job_after_job_from_one_interpreter(monkeypatch, tmp_path):
    """The packaged script itself, run as the child: each job gets its answer, one spawn."""
    spawned = []
    real_popen = detector_workers.subprocess.Popen

    def counting(argv, **kwargs):
        spawned.append(argv)
        return real_popen(argv, **kwargs)

    store = annotation_store()
    monkeypatch.setattr(detector_workers, "_IDLE", {})
    # WHY: counts spawns at the subprocess boundary; the real interpreter still starts.
    monkeypatch.setattr(detector_workers.subprocess, "Popen", counting)
    try:
        answers = [
            detectors.prepare_detectors(
                pending={detectors.MARQO_HEAD: [asset_id]},
                store=store,
                preview_paths=_previews(tmp_path, [asset_id]),
                python=sys.executable,
                cache_dir="",
                marqo_onnx=tmp_path / "absent-nsfw-marqo-384.onnx",
                allow_downloads=False,
                batch_size=16,
                check_cancelled=lambda: None,
                progress=lambda *_: None,
            )
            for asset_id in ("a", "b")
        ]
    finally:
        detector_workers.retire_detector_workers()

    assert len(spawned) == 1
    assert [detectors.MARQO_ONNX_ID in answer[detectors.MARQO_HEAD] for answer in answers] == [
        True,
        True,
    ]


def test_a_worker_that_died_before_its_first_job_still_names_why(tmp_path):
    broken = tmp_path / "python"
    broken.write_text("#!/bin/sh\necho 'No module named numpy' >&2\nexit 1\n")
    broken.chmod(0o700)
    worker = detector_workers._spawn(str(broken), "", False, 1)
    # The death lands in the log before the job is ever written: the race CI lost.
    worker.process.wait()

    with pytest.raises(RuntimeError, match="No module named numpy"):
        worker.run(tmp_path / "job.json", tmp_path / "result.json", lambda: None, lambda: None)
    worker.stop()


def test_an_interpreter_without_the_detector_dependencies_says_so(monkeypatch, tmp_path):
    broken = tmp_path / "python"
    broken.write_text("#!/bin/sh\necho 'No module named numpy' >&2\nexit 1\n")
    broken.chmod(0o700)
    monkeypatch.setattr(detector_workers, "_IDLE", {})

    with pytest.raises(RuntimeError, match="No module named numpy") as raised:
        detectors.prepare_detectors(
            pending={detectors.MARQO_HEAD: ["a"]},
            store=annotation_store(),
            preview_paths=_previews(tmp_path, ["a"]),
            python=str(broken),
            cache_dir="",
            marqo_onnx=tmp_path / "absent-nsfw-marqo-384.onnx",
            allow_downloads=False,
            batch_size=16,
            check_cancelled=lambda: None,
            progress=lambda *_: None,
        )

    assert "install required detector dependencies" in str(raised.value)
    assert detector_workers._IDLE == {}
