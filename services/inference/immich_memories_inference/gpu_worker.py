"""One CUDA worker address, retaining the existing service contracts."""

import asyncio
import gc
import sys
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from immich_memories_render_worker.app import create_app as render_app
from immich_memories_render_worker.native import NativeRenderer
from immich_memories_render_worker.renderer import Renderer
from immich_memories_render_worker.settings import WorkerSettings

from immich_memories.audio.generators.base import StemSeparator
from immich_memories_inference.app import create_app as inference_app
from immich_memories_inference.app import default_loaders
from immich_memories_inference.caption_proxy import register_captions
from immich_memories_inference.caption_runtime import CaptionRuntime
from immich_memories_inference.gpu_phases import GpuPhases, ModelAdmission
from immich_memories_inference.runtime import ProducerRuntime
from immich_memories_inference.settings import InferenceSettings


def create_app(
    settings: InferenceSettings,
    render_settings: WorkerSettings,
    *,
    runtime: ProducerRuntime | None = None,
    renderer: Renderer | None = None,
    audio_separator: StemSeparator | None = None,
    captions: CaptionRuntime | None = None,
) -> FastAPI:
    """Run both original lifespans and preserve render authentication under its prefix."""
    runtime = runtime or ProducerRuntime(
        default_loaders(settings), idle_unload_seconds=settings.idle_unload_seconds
    )
    inference = inference_app(settings, runtime=runtime, audio_separator=audio_separator)
    captions = captions or CaptionRuntime()

    def release(phase: str):
        if phase != "facts":
            runtime.unload_all()
        if phase != "caption":
            captions.stop()
        gc.collect()
        # Torch is optional in the CPU service and must stay unimported there.
        # In the CUDA worker Demucs may leave freed tensors in its allocator.
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.empty_cache()

    phases = GpuPhases(release)
    render = render_app(
        render_settings, renderer=PhaseRenderer(renderer or NativeRenderer(), phases)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            app.state.caption_http = await stack.enter_async_context(
                httpx.AsyncClient(
                    timeout=httpx.Timeout(300, connect=5), trust_env=False, follow_redirects=False
                )
            )
            stack.push_async_callback(asyncio.to_thread, captions.stop)
            await stack.enter_async_context(inference.router.lifespan_context(inference))
            await stack.enter_async_context(render.router.lifespan_context(render))
            yield

    app = FastAPI(title="Immich Memories CUDA worker", lifespan=lifespan)
    app.add_middleware(ModelAdmission, phases=phases)
    register_captions(app, captions)
    app.mount("/render", render)
    app.mount("/", inference)
    return app


class PhaseRenderer:
    """The existing render thread waits for model calls, then releases their weights."""

    def __init__(self, renderer: Renderer, phases: GpuPhases):
        self._renderer = renderer
        self._phases = phases

    def health(self):
        with self._phases.rendering():
            return self._renderer.health()

    def render(self, request, directory, progress):
        with self._phases.rendering():
            return self._renderer.render(request, directory, progress)


def main() -> None:
    """The optional CUDA-image entrypoint; standalone inference keeps its default."""
    settings = InferenceSettings()
    uvicorn.run(
        create_app(settings, WorkerSettings()),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
