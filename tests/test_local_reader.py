"""An owned local reader uses the same public transport as a hosted reader."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from immich_memories.analysis.llm_query import query_llm
from immich_memories.config_models_llm import LLMConfig


@pytest.fixture
def local_reader(tmp_path):
    # WHY: a real child HTTP server replaces model inference, without downloading weights.
    executable = tmp_path / "llama-server"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
        "from pathlib import Path\n"
        "args = dict(zip(sys.argv[1::2], sys.argv[2::2]))\n"
        "Path(__file__).with_suffix('.pid').write_text(str(os.getpid()))\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.reply({'data': [{'id': args['--alias']}]})\n"
        " def do_POST(self):\n"
        "  body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))\n"
        "  Path(__file__).with_suffix('.request').write_text(json.dumps(body))\n"
        "  self.reply({'choices': [{'message': {'content': 'yellow'}, 'finish_reason': 'stop'}]})\n"
        " def reply(self, body):\n"
        "  self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())\n"
        "HTTPServer((args['--host'], int(args['--port'])), Handler).serve_forever()\n"
    )
    executable.chmod(0o700)
    model = tmp_path / "reader.gguf"
    model.write_bytes(b"synthetic weights")
    return LLMConfig(enabled=True, base_url="", model=str(model), local_server=str(executable))


async def test_query_starts_owned_reader(local_reader):
    from immich_memories.local_inference import local_models

    try:
        assert await query_llm("What color is a banana?", local_reader) == "yellow"
        request = json.loads(Path(local_reader.local_server).with_suffix(".request").read_text())
        assert request["messages"][0]["content"] == "What color is a banana?"
    finally:
        await local_models.release()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="Owned readers support POSIX hosts")
async def test_failed_reader_startup_releases_surviving_child(local_reader):
    from immich_memories.local_inference import local_models

    # WHY: a real crashed model server leaves a child holding its native resources.
    executable = Path(local_reader.local_server)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, time\n"
        "from pathlib import Path\n"
        "pid_file = Path(__file__).with_suffix('.child')\n"
        "stopped = Path(__file__).with_suffix('.stopped')\n"
        "if os.fork() == 0:\n"
        " def stop(*args):\n"
        "  stopped.write_text('released'); os._exit(0)\n"
        " signal.signal(signal.SIGTERM, stop)\n"
        " pid_file.write_text(str(os.getpid()))\n"
        " while True: time.sleep(0.01)\n"
        "while not pid_file.exists(): time.sleep(0.01)\n"
        "os._exit(1)\n"
    )
    child_pid = None
    try:
        with pytest.raises(RuntimeError, match="exited during startup"):
            await query_llm("A reader that cannot start", local_reader)
        child_pid = int(executable.with_suffix(".child").read_text())
        for _ in range(20):
            if executable.with_suffix(".stopped").exists():
                break
            await asyncio.sleep(0.01)
        assert executable.with_suffix(".stopped").exists(), "Native child survived startup failure"
    finally:
        await local_models.release()
        if child_pid is None and executable.with_suffix(".child").exists():
            child_pid = int(executable.with_suffix(".child").read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("death", ["exit", "kill", "term"])
async def test_owned_reader_stops_when_its_app_disappears(local_reader, death):
    from immich_memories.local_inference import local_models

    executable = Path(local_reader.local_server)
    body = (
        executable.read_text()
        .replace("import json, os, sys", "import json, os, sys, signal")
        .replace(
            "class Handler(BaseHTTPRequestHandler):",
            "def stop(*args):\n"
            " Path(__file__).with_suffix('.stopped').write_text('released'); sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "class Handler(BaseHTTPRequestHandler):",
        )
    )
    executable.write_text(body)
    app_code = (
        "import asyncio, json, os, signal, sys\n"
        "from immich_memories.analysis.llm_query import query_llm\n"
        "from immich_memories.config_models_llm import LLMConfig\n"
        "config=LLMConfig.model_validate(json.loads(sys.argv[1]))\n"
        "asyncio.run(query_llm('one word', config))\n"
        + (
            "os._exit(7)\n"
            if death == "exit"
            else f"os.kill(os.getpid(), signal.{'SIGKILL' if death == 'kill' else 'SIGTERM'})\n"
        )
    )
    pid = None
    try:
        # WHY: a real application dies without Python cleanup, while its model is idle.
        app = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", app_code, local_reader.model_dump_json()],
            capture_output=True,
            timeout=20,
        )
        assert app.returncode in (7, -signal.SIGKILL, -signal.SIGTERM), app.stderr.decode()
        pid = int(executable.with_suffix(".pid").read_text())
        for _ in range(100):
            if executable.with_suffix(".stopped").exists():
                break
            await asyncio.sleep(0.05)
        assert executable.with_suffix(".stopped").exists(), "Reader survived app death"
    finally:
        await local_models.release()
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("endpoint", ["", "http://127.0.0.1:9/v1"])
async def test_disabled_llm_never_starts_or_contacts_a_server(local_reader, endpoint):
    from immich_memories.local_inference import local_models

    config = local_reader.model_copy(update={"enabled": False, "base_url": endpoint})
    try:
        with pytest.raises(ValueError, match="disabled"):
            await query_llm("Do not send this", config)
        assert not Path(local_reader.local_server).with_suffix(".pid").exists()
    finally:
        await local_models.release()


def test_enabling_without_a_model_reports_the_default_gemma_installation(tmp_path, monkeypatch):
    # WHY: model installation lives outside the repository; use an empty test home.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from immich_memories.config import Config
    from immich_memories.preflight import CheckStatus, check_llm

    config = Config(tier="full", llm={"enabled": True})
    report = check_llm(config)
    assert report.status == CheckStatus.ERROR
    assert "Gemma" in report.message or "llama.cpp" in report.message


def test_full_accepts_owned_reader_without_external_endpoint(local_reader):
    from immich_memories.config import Config
    from immich_memories.config_tiers import apply_tier
    from immich_memories.preflight import CheckStatus, check_llm

    config = Config(tier="full", llm=local_reader)
    apply_tier(config)
    check = check_llm(config)
    assert check.status == CheckStatus.OK
    assert "not tested" in check.message.lower()
    assert not Path(local_reader.local_server).with_suffix(".pid").exists()


async def test_warm_reader_keeps_each_requests_schema_policy(local_reader):
    from immich_memories.local_inference import local_models

    schema = {
        "type": "json_schema",
        "json_schema": {"name": "free_text", "schema": {"type": "object"}},
    }
    request_file = Path(local_reader.local_server).with_suffix(".request")
    pid_file = request_file.with_suffix(".pid")
    try:
        await query_llm("Structured", local_reader, response_format=schema)
        pid = pid_file.read_text()
        assert json.loads(request_file.read_text())["response_format"] == schema
        plain = local_reader.model_copy(update={"structured_output": False})
        await query_llm("Plain", plain, response_format=schema)
        assert "response_format" not in json.loads(request_file.read_text())
        assert pid_file.read_text() == pid
    finally:
        await local_models.release()


async def test_answers_survive_restart_but_not_changed_model_weights(local_reader):
    from immich_memories.local_inference import local_models
    from tests.annotation_rows import annotation_store

    bank = annotation_store()
    pid_file = Path(local_reader.local_server).with_suffix(".pid")
    try:
        await query_llm("The same question", local_reader, judgments=bank)
        await local_models.release()
        pid_file.unlink()
        await query_llm("The same question", local_reader, judgments=bank)
        assert not pid_file.exists()
        Path(local_reader.model).write_bytes(b"different weights")
        await query_llm("The same question", local_reader, judgments=bank)
        assert pid_file.exists()
    finally:
        await local_models.release()


async def test_local_music_frees_the_owned_reader_first(local_reader, tmp_path, monkeypatch):
    from immich_memories.audio.generators import ace_step_isolated
    from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig
    from immich_memories.audio.generators.base import GenerationRequest, GenerationResult
    from immich_memories.local_inference import local_models

    try:
        await query_llm("One word", local_reader)
        pid = int(Path(local_reader.local_server).with_suffix(".pid").read_text())

        from types import SimpleNamespace

        cleared = []
        # WHY: MLX is a native allocator boundary; the actual M2 run measured its idle cache.
        monkeypatch.setitem(
            sys.modules,
            "mlx.core",
            SimpleNamespace(
                clear_cache=lambda: cleared.append("clear"),
                synchronize=lambda: cleared.append("sync"),
            ),
        )

        async def generate(*args):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            assert cleared == ["clear", "sync"]
            return GenerationResult(tmp_path / "track.wav", metadata={"mode": "lib"})

        # WHY: replace only discovery and generation of the separate GPU audio environment.
        monkeypatch.setattr(ace_step_isolated, "isolated_python", lambda: tmp_path / "python")
        monkeypatch.setattr(ace_step_isolated, "generate_isolated", generate)
        async with ACEStepBackend(ACEStepConfig(mode="lib")) as backend:
            await backend.generate(GenerationRequest(output_dir=tmp_path))
    finally:
        await local_models.release()


def test_local_vision_setup_can_be_configured_before_weights_are_downloaded(tmp_path, monkeypatch):
    # WHY: this is a first-install test, regardless of models on the developer machine.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    from immich_memories.config import Config
    from immich_memories.preflight import CheckStatus, check_llm

    config = Config(
        tier="full", llm={"enabled": True}, editorial={"preparation": {"caption_provider": "llm"}}
    )
    assert check_llm(config).status == CheckStatus.ERROR


async def test_owned_vision_requests_keep_their_schema(local_reader):
    from immich_memories.local_inference import local_models

    schema = {
        "type": "json_schema",
        "json_schema": {"name": "caption", "schema": {"type": "object"}},
    }
    try:
        await query_llm(
            "Caption this", local_reader, images=(b"synthetic image",), response_format=schema
        )
        request = json.loads(Path(local_reader.local_server).with_suffix(".request").read_text())
        assert request["response_format"] == schema
        await query_llm(
            "Unconstrained image",
            local_reader.model_copy(update={"structured_output": False}),
            images=(b"synthetic image",),
            response_format=schema,
        )
        request = json.loads(Path(local_reader.local_server).with_suffix(".request").read_text())
        assert "response_format" not in request
    finally:
        await local_models.release()


async def test_cancelled_audio_keeps_reader_waiting_until_native_work_finishes(
    local_reader, tmp_path, monkeypatch
):
    from immich_memories.audio.generators import ace_step_isolated
    from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig
    from immich_memories.audio.generators.base import GenerationRequest, GenerationResult
    from immich_memories.local_inference import local_models

    started = asyncio.Event()
    finish = threading.Event()

    async def generate(*args):
        started.set()
        await asyncio.to_thread(finish.wait, 5)
        return GenerationResult(tmp_path / "track.wav", metadata={"mode": "lib"})

    # WHY: native GPU work keeps running when its Python awaiter is cancelled.
    monkeypatch.setattr(ace_step_isolated, "isolated_python", lambda: tmp_path / "python")
    monkeypatch.setattr(ace_step_isolated, "generate_isolated", generate)
    backend = ACEStepBackend(ACEStepConfig(mode="lib"))
    audio = asyncio.create_task(backend.generate(GenerationRequest(output_dir=tmp_path)))
    reader = None
    try:
        await asyncio.wait_for(started.wait(), 2)
        audio.cancel()
        reader = asyncio.create_task(query_llm("Wait for audio", local_reader))
        await asyncio.sleep(0.2)
        assert not audio.done(), "Cancellation must drain the native audio job"
        assert not Path(local_reader.local_server).with_suffix(".pid").exists()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await audio
        assert await reader == "yellow"
    finally:
        finish.set()
        await asyncio.gather(audio, *([reader] if reader else []), return_exceptions=True)
        await local_models.release()


@pytest.mark.extras
async def test_demucs_hands_memory_back_to_the_reader(local_reader, tmp_path, monkeypatch):
    from types import SimpleNamespace

    torch = pytest.importorskip("torch")
    pretrained = pytest.importorskip("demucs.pretrained")
    apply = pytest.importorskip("demucs.apply")
    import numpy as np
    import soundfile as sf

    from immich_memories.audio.generators.demucs_local import DemucsLocalBackend
    from immich_memories.local_inference import local_models

    backend = DemucsLocalBackend(device="cpu")
    try:
        await query_llm("Before stems", local_reader)
        pid = int(Path(local_reader.local_server).with_suffix(".pid").read_text())

        def get_model(_name):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            return SimpleNamespace(sources=["drums", "bass", "other", "vocals"])

        # WHY: replace downloaded Demucs weights/inference, retaining real WAV tensor I/O.
        monkeypatch.setattr(pretrained, "get_model", get_model)
        monkeypatch.setattr(
            apply, "apply_model", lambda _model, wav, **_kw: torch.stack([wav] * 4, dim=1)
        )
        source = tmp_path / "source.wav"
        sf.write(source, np.sin(np.arange(3200) / 10).astype("float32"), 16000)
        stems = await backend.separate_stems(source, tmp_path / "stems")
        assert stems.vocals.is_file()
        assert not (await backend.health_check())["loaded"]
        assert await query_llm("After stems", local_reader) == "yellow"
        assert int(Path(local_reader.local_server).with_suffix(".pid").read_text()) != pid
    finally:
        backend.release()
        await local_models.release()


def test_supervisor_releases_native_model_when_owner_pipe_closes(tmp_path, monkeypatch):
    from immich_memories.local_reader_process import supervise

    started = tmp_path / "started"
    released = tmp_path / "released"
    code = (
        "import signal, sys, time\n"
        "from pathlib import Path\n"
        "def stop(*args):\n"
        " Path(sys.argv[2]).write_text('released'); sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "Path(sys.argv[1]).write_text('resident')\n"
        "while True: time.sleep(0.01)\n"
    )
    read_end, write_end = os.pipe()
    handlers = {kind: signal.getsignal(kind) for kind in (signal.SIGTERM, signal.SIGINT)}

    def app_disappears():
        for _ in range(100):
            if started.exists():
                break
            threading.Event().wait(0.01)
        os.close(write_end)

    with os.fdopen(read_end) as owner:
        # WHY: the inherited application-lifetime pipe is an external OS boundary.
        monkeypatch.setattr(sys, "stdin", owner)
        closer = threading.Thread(target=app_disappears)
        closer.start()
        try:
            assert supervise([sys.executable, "-c", code, str(started), str(released)]) == 0
            assert released.read_text() == "released"
        finally:
            closer.join(timeout=2)
            for kind, handler in handlers.items():
                signal.signal(kind, handler)


async def test_render_handoff_reaps_reader_then_music_prompt_reloads(local_reader, monkeypatch):
    from types import SimpleNamespace

    from immich_memories.local_inference import local_models

    cleared = []
    # WHY: only the allocator boundary is replaced; the reader is a real owned process.
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(
        sys.modules,
        "mlx.core",
        SimpleNamespace(
            clear_cache=lambda: cleared.append("clear"),
            synchronize=lambda: cleared.append("sync"),
        ),
    )
    try:
        assert await query_llm("Select a story", local_reader) == "yellow"
        process = local_models._process
        assert process is not None and process.poll() is None
        await local_models.release(unused_buffers=True)
        assert process.poll() is not None
        assert local_models._process is None
        assert cleared == ["clear", "sync"]
        assert await query_llm("Describe the music", local_reader) == "yellow"
        assert local_models._process is not None
        assert local_models._process is not process
        assert local_models._process.poll() is None
    finally:
        await local_models.release()
