"""The audience check's activity reader scores each caption once and keeps its model open (#2695)."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories.analysis.audience import verdicts
from immich_memories.analysis.audience.laya_reader import LayaReader
from immich_memories.analysis.audience.verdicts import AudienceBank, AudienceGate
from immich_memories.analysis.film.contract import StructurePlannerPorts
from immich_memories.analysis.reading.annotation_lines import AssetAnnotationLine
from immich_memories.analysis.structure.planner import plan_structure
from immich_memories.db import open_store
from tests.editorial_story_fixtures import ControlledStoryJudge
from tests.editorial_thin_fixtures import CountingJudge, caption_laya
from tests.test_editorial_duration_planner_integration import source


class _CountingScorer:
    """# WHY: replaces the trained checkpoint; a caption naming a bath is a bathing hold."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def probabilities(self, states, question):
        self.batches.append(list(states))
        names = list(question["criteria"])
        return [
            [1.0 if name == ("bathing" if "bath" in s else "none") else 0.0 for name in names]
            for s in states
        ]


def _line(asset_id, caption, heads=()):
    return AssetAnnotationLine(asset_id, f"09:00 | {caption}", caption, tuple(heads))


def _gate(tmp_path, annotations, reader, *, answerer="full|laya"):
    return AudienceGate(
        CountingJudge(),
        audience="family",
        annotations=annotations,
        flag_rows={},
        lines={a: n.text for a, n in annotations.items()},
        bank_path=tmp_path / "shareability.private.json",
        library=AudienceBank(open_store(), answerer=answerer),
        activity_reader=reader.activity_answers,
    )


def test_a_carrier_whose_evidence_changes_after_its_batch_is_not_scored_again(tmp_path):
    scorer = _CountingScorer()
    reader = LayaReader(scorer, threshold=0.186, checkpoint_id="test-checkpoint")
    annotations = {
        "a": _line("a", "A child plays with a red ball."),
        "b": _line("b", "A child sits in a bath."),
    }
    gate = _gate(tmp_path, annotations, reader)
    units = [{"asset_id": "a"}, {"asset_id": "b"}]

    gate.prefetch(units, batch=16)
    # A later preparation round banks a fact about the picture: its evidence key changes,
    # its caption does not, and the caption is all the activity question reads.
    annotations["a"] = _line("a", "A child plays with a red ball.", (("nsfw_marqo", "no"),))
    verdict_a, verdict_b = gate.verdict_of(units[0]), gate.verdict_of(units[1])

    assert [len(batch) for batch in scorer.batches] == [2]
    fresh = _gate(
        tmp_path / "fresh",
        annotations,
        LayaReader(_CountingScorer(), threshold=0.186, checkpoint_id="x"),
        answerer="a reader that banked nothing yet",
    )
    assert (verdict_a, verdict_b) == (fresh.verdict_of(units[0]), fresh.verdict_of(units[1]))


def test_the_same_caption_is_scored_once_across_cuts_by_one_reader(tmp_path):
    scorer = _CountingScorer()
    reader = LayaReader(scorer, threshold=0.186, checkpoint_id="test-checkpoint")
    pending = {"k1": (["A dog runs."], True), "k2": (["A dog runs."], True)}

    first = reader.activity_answers(pending)
    second = reader.activity_answers({"k3": (["A dog runs."], True)})

    assert [len(batch) for batch in scorer.batches] == [1]
    assert first["k1"] == first["k2"] == second["k3"]


def _film(tmp_path, monkeypatch, *, pictures=20, audience="family"):
    # Each film banks its answers in its own library, so neither run reads the other's.
    tmp_path.mkdir()
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    captured = replace(
        source(tmp_path, seconds=60, pictures=pictures, private_opening=True), audience=audience
    )
    prepared: set[str] = set()

    def prepare(rows):
        # WHY: the preparation boundary; the planner, the gates and the reader are real.
        fresh = {row["asset_id"] for row in rows} - prepared
        prepared.update(fresh)
        return bool(fresh)

    laya = caption_laya()
    prints = {f"picture-{n:03}": np.eye(pictures)[0 if n == 1 else n] for n in range(pictures)}
    plan = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda a: hashlib.sha256(a.encode()).hexdigest()[:16],
            scene_print=prints.get,
            prepare_candidates=prepare,
            laya=laya,
        ),
    ).plan
    cut = [row["asset_id"] for row in plan["carriers"]]
    shown = {asset: v["verdict"] for asset, v in plan["shareability"]["verdicts"].items()}
    return cut, shown, laya.scorer


@pytest.mark.parametrize("audience", ["family", "shareable"])
def test_the_film_s_carriers_are_read_in_batches_with_the_same_cut(tmp_path, monkeypatch, audience):
    batched_cut, batched_verdicts, batched = _film(
        tmp_path / "batched", monkeypatch, audience=audience
    )
    # As before: the carriers prepared in one round, then read one at a time.
    monkeypatch.setattr(verdicts.AudienceGate, "read_ahead", verdicts.AudienceGate.prepare)
    single_cut, single_verdicts, single = _film(tmp_path / "single", monkeypatch, audience=audience)

    assert batched_cut == single_cut
    assert batched_verdicts == single_verdicts
    assert sorted(batched.states) == sorted(single.states)
    assert "just_us" in batched_verdicts.values()
    assert single.calls == len(single.states) > 2
    # The film's carriers in one batch, the held opener's replacements in another.
    assert batched.calls == 2


@pytest.fixture
def onnx_checkpoint(tmp_path, monkeypatch):
    """A tiny tokenizer and a stand-in ONNX Runtime that counts the sessions it opens."""
    from tokenizers import Tokenizer, models, pre_tokenizers

    folder = tmp_path / "laya"
    (folder / "tokenizer").mkdir(parents=True)
    vocabulary = ["[UNK]", "[CLS]", "[SEP]", "[PAD]", "[MASK]", "bath", "picnic"]
    tokenizer = Tokenizer(
        models.WordLevel(dict(zip(vocabulary, range(len(vocabulary)), strict=True)), "[UNK]")
    )
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.save(str(folder / "tokenizer" / "tokenizer.json"))
    special = {"cls_token": "[CLS]", "sep_token": "[SEP]", "pad_token": "[PAD]"}
    (folder / "tokenizer" / "tokenizer_config.json").write_text(
        json.dumps(special | {"mask_token": "[MASK]"})
    )
    (folder / "rl_agent_config.json").write_text(json.dumps({"max_len": 256, "head_max_len": 192}))
    (folder / "model.onnx").write_bytes(b"graph")
    (folder / "model.onnx.data").write_bytes(b"weights")
    opened: list[dict] = []

    class Session:
        # WHY: substitutes the model execution boundary; tokenizer and packing are real.
        def __init__(self, path, **kwargs):
            opened.append(kwargs)

        def run(self, names, feed):
            return [np.zeros((len(feed["input_ids"]), 10), dtype=np.float32)]

        def get_providers(self):
            return ["CPUExecutionProvider"]

    class Options:
        intra_op_num_threads = 0
        inter_op_num_threads = 0
        graph_optimization_level = None

    # WHY: ONNX Runtime is the native boundary; this counts what the scorer opens on it.
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            get_available_providers=lambda: ["CPUExecutionProvider"],
            disable_telemetry_events=lambda: None,
            InferenceSession=Session,
            SessionOptions=Options,
            GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
        ),
    )
    return folder, opened


def test_the_onnx_session_opens_once_across_closes_and_scorers(onnx_checkpoint, monkeypatch):
    from immich_memories.analysis.audience import laya_onnx
    from immich_memories.analysis.audience.laya_onnx import OnnxLayaScorer
    from immich_memories.analysis.audience.laya_reader import AUDIENCE_QUESTION

    folder, opened = onnx_checkpoint
    # WHY: the container's CPU limit, which the session's thread pool must follow.
    monkeypatch.setattr("immich_memories.onnx_session.available_cpus", lambda: 3)
    first = OnnxLayaScorer(folder)
    first.probabilities(["bath"], AUDIENCE_QUESTION)
    # Each edit closes its effects; a CPU session is kept for the next one.
    first.close()
    first.probabilities(["picnic"], AUDIENCE_QUESTION)
    OnnxLayaScorer(folder).probabilities(["picnic"], AUDIENCE_QUESTION)

    assert len(opened) == 1
    assert opened[0]["sess_options"].intra_op_num_threads == 2

    # Selection hands the machine to the render: the session goes, and the next film opens it.
    from immich_memories.local_inference import LocalModels

    LocalModels().prepare_audio()
    OnnxLayaScorer(folder).probabilities(["bath"], AUDIENCE_QUESTION)
    assert len(opened) == 2
    laya_onnx.release_sessions()


def test_one_reader_per_checkpoint_hashes_its_files_once(onnx_checkpoint, monkeypatch, tmp_path):
    from immich_memories.analysis.audience import laya_reader
    from immich_memories.config.models.editorial import EditorialConfig

    folder, _opened = onnx_checkpoint
    hashed = []
    real = laya_reader.checkpoint_identity

    def counted(path):
        hashed.append(path)
        return real(path)

    # WHY: counts the fingerprint of the checkpoint files (gigabytes on a real install).
    monkeypatch.setattr(laya_reader, "checkpoint_identity", counted)
    config = EditorialConfig(laya_audience=True, laya_checkpoint=str(folder))

    first, second = laya_reader.laya_reader_for(config), laya_reader.laya_reader_for(config)
    assert first is second
    assert len(hashed) == 1

    (folder / "model.onnx.data").write_bytes(b"other weights")
    third = laya_reader.laya_reader_for(config)
    assert third is not first
    assert third.cache_identity != first.cache_identity
    assert len(hashed) == 2
    stricter = laya_reader.laya_reader_for(
        config.model_copy(update={"laya_audience_threshold": 0.5})
    )
    assert stricter is not third
