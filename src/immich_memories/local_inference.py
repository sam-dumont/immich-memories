"""Own one local model process and serialize access across reader event loops."""

from __future__ import annotations

import asyncio
import atexit
import gc
import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

import httpx

from immich_memories.config_models_llm import DEFAULT_LOCAL_MODEL, LLMConfig
from immich_memories.operations.bounded_process import stop_process_group

_Result = TypeVar("_Result")


async def finish_model_work(work: Awaitable[_Result]) -> _Result:
    """Drain native work before cancellation can release its model's memory lease."""
    task = asyncio.ensure_future(work)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            if not cancelled:
                raise
    if cancelled:
        if not task.cancelled():
            task.exception()  # Retrieve a failure without replacing the caller's cancellation.
        raise asyncio.CancelledError
    return task.result()


def local_reader_paths(config: LLMConfig) -> list[Path]:
    """Resolve the default Gemma pair or explicitly supplied GGUF paths."""
    if config.model == DEFAULT_LOCAL_MODEL:
        root = Path.home() / ".immich-memories/models/reader"
        projector = (
            Path(config.local_mmproj).expanduser().resolve()
            if config.local_mmproj
            else root / "mmproj-gemma-4-E4B-it-Q8_0.gguf"
        )
        return [root / f"{DEFAULT_LOCAL_MODEL}.gguf", projector]
    return [Path(p).expanduser().resolve() for p in (config.model, config.local_mmproj) if p]


@lru_cache(maxsize=8)
def _weight_digest(path: Path, _signature: tuple[int, ...]) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_reader_identity(config: LLMConfig) -> tuple:
    """Reuse answers across restarts, but never across different weights or context limits."""
    digests = []
    for path in local_reader_paths(config):
        try:
            stat = path.stat()
        except FileNotFoundError:
            # Configuration and models fetch must work before installation. This
            # identity cannot match any answer produced from actual model bytes.
            digests.append(f"missing:{path}")
        else:
            digests.append(_weight_digest(path, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)))
    return ("llama.cpp-v1", config.local_context, *digests)


def local_reader_files(config: LLMConfig) -> tuple[str, list[Path]]:
    """Check the local installation without downloading or loading model weights."""
    if sys.platform not in {"darwin", "linux"}:
        raise RuntimeError("Owned local inference supports Linux and macOS")
    executable = shutil.which(config.local_server)
    if not executable:
        raise FileNotFoundError("Install llama.cpp and put llama-server on PATH")
    files = local_reader_paths(config)
    if not files:
        raise ValueError("Choose a local GGUF model or the default Gemma model")
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f"Local Gemma/GGUF file is missing: {path}. Run models fetch")
    return executable, files


class LocalModels:
    """Keep a reader warm between calls, then release it at render and audio boundaries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._directory: tempfile.TemporaryDirectory | None = None
        self._settings: tuple | None = None
        self._endpoint: LLMConfig | None = None

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        """Wait without blocking another event loop's request or leaking a cancelled waiter."""
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            self._lock.release()

    @asynccontextmanager
    async def reader(self, config: LLMConfig) -> AsyncIterator[LLMConfig]:
        """Lazily start the configured reader and lease it for the complete HTTP request."""
        # The owned server is llama.cpp, not an unknown loopback provider such as oMLX.
        if config.structured_output is None:
            config = config.model_copy(update={"structured_output": True})
        async with self.exclusive():
            try:
                yield await self._start(config)
            except BaseException:
                self.close()
                raise

    async def release(self, *, unused_buffers: bool = False) -> None:
        """Drain leased work, then release the owned reader and optionally runtime buffers."""
        async with self.exclusive():
            if unused_buffers:
                self.prepare_audio()
            else:
                self.close()

    def close(self) -> None:
        """Reap the owned process group, including on interpreter exit."""
        process, self._process = self._process, None
        if process is not None:
            stop_process_group(process, terminate_grace_seconds=10, kill_grace_seconds=10)
            if process.stdin is not None:
                process.stdin.close()
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self._settings = self._endpoint = None

    def prepare_audio(self) -> None:
        """Release the owned reader and unused buffers in already-loaded local runtimes."""
        self.close()
        # Model loaders can leave cyclic Python owners after their live tensors are dropped.
        # Collect those owners before asking each allocator to return unused buffers.
        gc.collect()
        if torch := sys.modules.get("torch"):
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        if mlx := sys.modules.get("mlx.core"):
            # Planning can drop every Laya tensor while retaining gigabytes of idle Metal cache.
            mlx.clear_cache()
            mlx.synchronize()

    async def _start(self, config: LLMConfig) -> LLMConfig:
        executable, files = local_reader_files(config)
        settings = (executable, local_reader_identity(config))
        if self._process and self._process.poll() is None and self._settings == settings:
            assert self._endpoint is not None
            return config.model_copy(
                update={
                    name: getattr(self._endpoint, name) for name in ("base_url", "api_key", "model")
                }
            )
        self.close()
        self._directory = tempfile.TemporaryDirectory(prefix="immich-reader-")
        directory = Path(self._directory.name)
        key = secrets.token_urlsafe(32)
        key_file = directory / "key"
        key_file.write_text(key)
        key_file.chmod(0o600)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        alias = files[0].stem
        command = [
            executable,
            "--model",
            str(files[0]),
            "--alias",
            alias,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--parallel",
            "1",
            "--ctx-size",
            str(config.local_context),
            "--cache-ram",
            "128",
            "--api-key-file",
            str(key_file),
        ]
        if len(files) > 1:
            command.extend(["--mmproj", str(files[1])])
        with (directory / "server.log").open("w") as log:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "immich_memories.local_reader_process", *command],
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={k: v for k, v in os.environ.items() if not k.startswith("LLAMA_")},
            )
        endpoint = config.model_copy(
            update={
                "base_url": f"http://127.0.0.1:{port}/v1",
                "api_key": key,
                "model": alias,
            }
        )
        await self._ready(endpoint, directory)
        self._settings, self._endpoint = settings, endpoint
        return endpoint

    async def _ready(self, endpoint: LLMConfig, directory: Path) -> None:
        deadline = time.monotonic() + 180
        async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
            while time.monotonic() < deadline:
                assert self._process is not None
                if self._process.poll() is not None:
                    detail = (directory / "server.log").read_text(errors="replace")[-2000:]
                    raise RuntimeError(f"Local reader exited during startup: {detail}")
                try:
                    response = await client.get(
                        f"{endpoint.base_url}/models",
                        headers={"Authorization": f"Bearer {endpoint.api_key}"},
                    )
                    if response.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
        raise TimeoutError("Local reader did not become ready within 180 seconds")


local_models = LocalModels()
atexit.register(local_models.close)
