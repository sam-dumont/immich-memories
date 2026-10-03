"""Selection models release their native state before rendering needs the device."""

import asyncio
import gc
import sys
import weakref
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace

import pytest

from immich_memories.analysis.editorial_laya_reader import LayaReader, MlxLayaScorer
from immich_memories.analysis.selection_trace import Trace
from immich_memories.generate import GenerationError, generate_memory
from immich_memories.local_inference import LocalModels
from tests.annotation_rows import annotation_store
from tests.test_editorial_duration_planner_integration import source
from tests.test_editorial_laya_reader import _fake_laya_mlx
from tests.test_editorial_planning_incomplete import backend_for, partial_result
from tests.test_generate_coverage import TestGenerateMemoryRun as _GenerationHarness


def test_mlx_close_drops_live_weights_and_reloads_identically(monkeypatch, tmp_path):
    # WHY: replace only the optional model/runtime boundary; score and lifetime are real.
    _fake_laya_mlx(monkeypatch)
    scorer = MlxLayaScorer(tmp_path)
    reader = LayaReader(scorer, threshold=0.186, checkpoint_id="weights")
    identity = reader.cache_identity
    pending = {"one": (["a caption"], True)}
    before = reader.activity_answers(pending)
    agent = weakref.ref(scorer._agent)

    reader.close()
    reader.close()

    assert agent() is None
    assert reader.cache_identity == identity
    assert reader.activity_answers(pending) == before
    assert scorer._agent is not None
    reader.close()


@pytest.mark.parametrize("reader_mode", ["rules", "model"])
@pytest.mark.parametrize("failed", [False, True])
def test_production_selection_closes_each_laya_effect_on_success_or_failure(
    monkeypatch, tmp_path, reader_mode, failed
):
    captured = source(tmp_path, seconds=60, pictures=3)
    captured = replace(captured, store=annotation_store())
    captured.config.editorial.reader = reader_mode
    captured.config.editorial.preparation.tier = "full"
    backend = backend_for(captured, partial_result(captured))
    readers = []

    class Scorer:
        # WHY: the native checkpoint boundary. The backend and its cleanup scope are real.
        def __init__(self):
            self.loaded = True
            self.closes = 0

        def close(self):
            self.loaded = False
            self.closes += 1

    def load(_config):
        scorer = Scorer()
        reader = LayaReader(scorer, threshold=0.186, checkpoint_id="weights")
        readers.append((reader, scorer))
        return reader

    monkeypatch.setattr("immich_memories.analysis.editorial_laya_reader.laya_reader_for", load)
    backend._ports = replace(backend._ports, structure_ports_factory=None)
    # Keep the effects referenced across cleanup, as refinement closures can do.
    effects = []
    with (
        pytest.raises(RuntimeError, match="failed") if failed else ExitStack(),
        ExitStack() as resources,
    ):
        effects.extend(backend._effects(captured, resources) for _ in range(2))
        assert all(
            effect.laya is reader for effect, (reader, _) in zip(effects, readers, strict=True)
        )
        assert all(scorer.loaded for _, scorer in readers)
        if failed:
            raise RuntimeError("failed")
    assert len(readers) == 2
    assert all(not scorer.loaded and scorer.closes == 1 for _, scorer in readers)

    # The real edit finally also releases an effect still retained by the planner.
    def planner(_source, ports):
        effects.append(ports)
        if failed:
            raise RuntimeError("failed")
        return partial_result(captured)

    backend._ports = replace(backend._ports, structure_planner=planner)
    # WHY: adoption writes the selected film; this test stops at the resource lifetime seam.
    monkeypatch.setattr(backend, "_adopt", lambda result, *_args: result)
    with pytest.raises(RuntimeError, match="failed") if failed else ExitStack():
        backend.edit(captured, trace=Trace())
    assert len(readers) == 3
    assert all(not scorer.loaded and scorer.closes == 1 for _, scorer in readers)


async def test_buffer_release_waits_for_leased_work_and_can_be_reused(monkeypatch):
    models = LocalModels()
    events = []
    monkeypatch.setattr(models, "close", lambda: events.append("reader"))
    # WHY: substitute the already-loaded MLX allocator, without importing a GPU runtime.
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(
        sys.modules,
        "mlx.core",
        SimpleNamespace(
            clear_cache=lambda: events.append("cache"), synchronize=lambda: events.append("sync")
        ),
    )
    async with models.exclusive():
        release = asyncio.create_task(models.release(unused_buffers=True))
        await asyncio.sleep(0.01)
        assert events == []
        assert not release.done()
    await asyncio.wait_for(release, 2)
    assert events == ["reader", "cache", "sync"]
    async with models.exclusive():
        events.append("reuse")
    await models.release()
    assert events[-2:] == ["reuse", "reader"]


@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("failed", [False, True])
async def test_generation_releases_selection_buffers_before_render_even_with_active_loop(
    monkeypatch, tmp_path, deferred, failed
):
    helper = _GenerationHarness()
    params = helper._make_params(tmp_path, no_music=True)
    patches, _, _ = helper._patch_inner_deps(tmp_path)
    events = []

    async def release(*, unused_buffers=False):
        assert unused_buffers
        events.append("release")

    def render(*args):
        assert events == ["release"]
        events.append("render")
        raise GenerationError("stop at render")

    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    with ExitStack() as stack:
        mocks = {name: stack.enter_context(patch) for name, patch in patches.items()}
        # WHY: rendering is the GPU/media boundary; no film needs encoding for this ordering test.
        monkeypatch.setattr("immich_memories.generate_render.render_base", render)
        if failed:

            async def fail_release(**kwargs):
                raise RuntimeError("release failed")

            monkeypatch.setattr(
                "immich_memories.local_inference.local_models.release", fail_release
            )
        with pytest.raises(GenerationError, match="release failed" if failed else "stop at render"):
            generate_memory(
                params, run_tracker=mocks["tracker"].return_value, defer_finalization=deferred
            )
    assert events == ([] if failed else ["release", "render"])


def test_audio_handoff_collects_cyclic_model_owners_before_clearing_buffers(monkeypatch):
    class Owner:
        pass

    owner = Owner()
    owner.cycle = owner
    reference = weakref.ref(owner)
    cleared = []

    def clear_cache():
        assert reference() is None
        cleared.append(True)

    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(
        sys.modules, "mlx.core", SimpleNamespace(clear_cache=clear_cache, synchronize=lambda: None)
    )
    # Disable automatic collection so the test exercises the handoff's explicit collection.
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        del owner
        assert reference() is not None
        LocalModels().prepare_audio()
        assert cleared == [True]
    finally:
        if was_enabled:
            gc.enable()
