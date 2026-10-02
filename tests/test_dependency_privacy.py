"""Dependency cache reads must not turn into unrequested telemetry calls."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CACHE_READ = """
import importlib
import socket
import sys

connections = []
# WHY: refuse real outside socket writes, including errors a dependency swallows.
def refuse(self, address):
    connections.append(address)
    raise OSError("network disabled by privacy regression")
socket.socket.connect = refuse
socket.socket.connect_ex = refuse
importlib.import_module(sys.argv[1])
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import LocalEntryNotFoundError
try:
    hf_hub_download("privacy-test/missing", "absent.bin", local_files_only=True)
except LocalEntryNotFoundError:
    pass
else:
    raise AssertionError("fresh cache unexpectedly contains the model")
assert not connections, connections
"""


def run_fresh(tmp_path, code, package, *, inherited="0"):
    pytest.importorskip("huggingface_hub")
    env = os.environ.copy()
    env.pop("HF_HUB_OFFLINE", None)
    env.pop("HF_HUB_DISABLE_TELEMETRY", None)
    if inherited is not None:
        env["HF_HUB_DISABLE_TELEMETRY"] = inherited
    env["HF_HOME"] = str(tmp_path)
    env["HF_HUB_CACHE"] = str(tmp_path / "hub")
    env["PYTHONPATH"] = os.pathsep.join(
        str(ROOT / path) for path in ("src", "services/inference", "services/render-worker")
    )
    result = subprocess.run(
        [sys.executable, "-c", code, package],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("inherited", [None, "0"])
def test_local_model_cache_read_never_calls_agent_registry(tmp_path, inherited):
    run_fresh(tmp_path, CACHE_READ, "immich_memories", inherited=inherited)


@pytest.mark.parametrize("package", ["immich_memories_inference", "immich_memories_render_worker"])
@pytest.mark.parametrize("inherited", [None, "0"])
def test_service_cache_reads_never_send_dependency_telemetry(tmp_path, package, inherited):
    run_fresh(tmp_path, CACHE_READ, package, inherited=inherited)


DOWNLOAD = """
import importlib
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

connections = []
connect = socket.socket.connect
# WHY: permit the explicitly selected model host, refuse any telemetry destination.
def guarded(self, address):
    if address[0] != "127.0.0.1":
        connections.append(address)
        raise OSError("unrequested external connection")
    return connect(self, address)
socket.socket.connect = guarded
importlib.import_module(sys.argv[1])
from huggingface_hub import hf_hub_download

class ModelHost(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("X-Repo-Commit", "a" * 40)
        self.send_header("ETag", '"' + "b" * 40 + '"')
        self.send_header("Content-Length", "5")
        self.end_headers()
    def do_GET(self):
        self.do_HEAD()
        self.wfile.write(b"model")
    def log_message(self, *args):
        pass

host = ThreadingHTTPServer(("127.0.0.1", 0), ModelHost)
thread = Thread(target=host.serve_forever, daemon=True)
thread.start()
try:
    model = hf_hub_download(
        "privacy-test/model", "weights.bin",
        endpoint="http://127.0.0.1:" + str(host.server_port),
        local_files_only=False,
    )
    assert Path(model).read_bytes() == b"model"
    assert not connections, connections
finally:
    host.shutdown()
    host.server_close()
    thread.join()
"""


@pytest.mark.parametrize(
    "package", ["immich_memories", "immich_memories_inference", "immich_memories_render_worker"]
)
def test_explicit_model_download_still_works_without_dependency_telemetry(tmp_path, package):
    run_fresh(tmp_path, DOWNLOAD, package)
