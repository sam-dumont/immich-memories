"""GPU ownership between existing queues; native work is never unloaded mid-call."""

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class PhaseBusy(RuntimeError):
    """Another phase still owns the GPU; existing callers can retry."""


class GpuPhases:
    """Admission only: the inference and render services retain their own queues."""

    def __init__(self, release: Callable[[str], None], timeout: float = 60):
        self._release = release
        self._timeout = timeout
        self._condition = threading.Condition()
        self._active = 0
        self._phase = ""
        self._preparing = False
        self._render_waiting = False

    @asynccontextmanager
    async def models(self, phase: str):
        with self._condition:
            if self._render_waiting or (self._active and self._phase != phase):
                raise PhaseBusy("GPU is busy with another phase")
            transition = self._phase != phase
            waiting = self._preparing
            self._phase = phase
            self._active += 1
            self._preparing = self._preparing or transition
        try:
            if transition:
                work = asyncio.create_task(asyncio.to_thread(self._release, phase))
                try:
                    await asyncio.shield(work)
                except asyncio.CancelledError:
                    await work
                    raise
                except Exception:
                    with self._condition:
                        self._phase = ""
                    raise
                finally:
                    with self._condition:
                        self._preparing = False
                        self._condition.notify_all()
            elif waiting:
                await asyncio.to_thread(self._wait_for_preparation, phase)
            yield
        finally:
            self._leave()

    def _wait_for_preparation(self, phase: str):
        with self._condition:
            if not self._condition.wait_for(lambda: not self._preparing, timeout=self._timeout):
                raise PhaseBusy("GPU phase cleanup did not finish before the admission deadline")
            if self._phase != phase:
                raise PhaseBusy("GPU phase cleanup failed")

    @contextmanager
    def rendering(self):
        with self._condition:
            self._render_waiting = True
            if not self._condition.wait_for(lambda: not self._active, timeout=self._timeout):
                self._render_waiting = False
                raise PhaseBusy("GPU model work did not finish before the render deadline")
            self._phase = "render"
            self._active = 1
            self._render_waiting = False
        try:
            self._release("render")
            yield
        finally:
            try:
                # Retain admission until native title buffers have been returned to the GPU.
                self._release("idle")
            finally:
                self._leave()

    def _leave(self):
        with self._condition:
            self._active -= 1
            self._condition.notify_all()


class ModelAdmission:
    """ASGI boundary retains ownership until the actual endpoint finishes native work."""

    def __init__(self, app, phases: GpuPhases):
        self.app = app
        self.phases = phases
        self._requests: set[asyncio.Task] = set()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        phase = _model_phase(path)
        if scope["type"] != "http" or not phase:
            await self.app(scope, receive, send)
            return
        # Client cancellation cannot cancel an in-process native model call.
        # Keep the actual endpoint and its ownership alive independently; the
        # existing queue still controls admission and native completion.
        work = asyncio.create_task(self._serve(phase, scope, receive, send))
        self._requests.add(work)
        work.add_done_callback(self._finished)
        await asyncio.shield(work)

    async def _serve(self, phase, scope, receive, send):
        try:
            async with self.phases.models(phase):
                await self.app(scope, receive, send)
        except PhaseBusy:
            await JSONResponse(
                {"detail": "GPU is busy with another phase"},
                status_code=503,
                headers={"Retry-After": "1"},
            )(scope, receive, send)

    def _finished(self, work: asyncio.Task):
        self._requests.discard(work)
        if not work.cancelled() and (error := work.exception()) is not None:
            logger.warning("GPU model request failed (%s)", type(error).__name__)


def _model_phase(path: str) -> str:
    if path == "/facts":
        return "facts"
    if path == "/audio/stems":
        return "audio"
    if path.startswith("/v1/"):
        return "caption"
    return ""
