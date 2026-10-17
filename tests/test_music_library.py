"""The music-v2 library: resolution order, pinned install, safe unpacking, the plan."""

from __future__ import annotations

import hashlib
import http.server
import io
import tarfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from immich_memories.audio import bundled_music
from immich_memories.config.loader import Config
from immich_memories.model_acquisition import acquisition_plan
from immich_memories.music_library import (
    MARKER,
    MUSIC_DIR_ENV,
    MUSIC_V2_MOODS,
    install_music_v2,
    installed_music_v2,
    music_v2_dir,
)
from immich_memories.pinned_models import MUSIC_V2


def _tar(entries: dict[str, bytes | None], extra: Callable[[tarfile.TarFile], None] | None = None):
    """A small archive; a None body makes a directory entry."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for name, body in entries.items():
            info = tarfile.TarInfo(name)
            if body is None:
                info.type = tarfile.DIRTYPE
                bundle.addfile(info)
            else:
                info.size = len(body)
                bundle.addfile(info, io.BytesIO(body))
        if extra:
            extra(bundle)
    return buffer.getvalue()


def _library_entries() -> dict[str, bytes | None]:
    entries: dict[str, bytes | None] = {"music-v2/": None, "music-v2/LICENSE-MUSIC": b"MIT"}
    for mood in MUSIC_V2_MOODS:
        entries[f"music-v2/{mood}/"] = None
        entries[f"music-v2/{mood}/{mood}_a.opus"] = b"opus"
    return entries


class _Server:
    def __init__(self, body: bytes) -> None:
        self.requests = 0
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                server.requests += 1
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}/music.tar"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def serve() -> Iterator[Callable[[bytes], _Server]]:
    servers: list[_Server] = []

    def start(body: bytes) -> _Server:
        servers.append(_Server(body))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def test_install_unpacks_a_pinned_archive_and_marks_it_complete(serve, tmp_path: Path) -> None:
    body = _tar(_library_entries())
    server = serve(body)
    target = tmp_path / "music-v2"

    outcome = install_music_v2(target, url=server.url, sha256=_sha(body))

    assert outcome == "downloaded"
    assert (target / "calm" / "calm_a.opus").read_bytes() == b"opus"
    assert (target / "LICENSE-MUSIC").is_file()
    assert installed_music_v2(target, sha256=_sha(body)) == target
    assert [p.name for p in tmp_path.iterdir()] == ["music-v2"]


def test_install_is_a_no_op_until_forced(serve, tmp_path: Path) -> None:
    body = _tar(_library_entries())
    server = serve(body)
    target = tmp_path / "music-v2"
    install_music_v2(target, url=server.url, sha256=_sha(body))

    assert install_music_v2(target, url=server.url, sha256=_sha(body)) == "present"
    assert server.requests == 1
    assert install_music_v2(target, url=server.url, sha256=_sha(body), force=True) == "downloaded"
    assert server.requests == 2


def test_a_digest_mismatch_installs_nothing(serve, tmp_path: Path) -> None:
    server = serve(_tar(_library_entries()))
    target = tmp_path / "music-v2"

    with pytest.raises(ValueError, match="is not the pinned"):
        install_music_v2(target, url=server.url, sha256="0" * 64)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "bad_name",
    ["music-v2/../escape.opus", "/etc/escape.opus", "other/calm/a.opus"],
)
def test_unpacking_refuses_names_outside_the_library(serve, tmp_path: Path, bad_name: str) -> None:
    body = _tar({**_library_entries(), bad_name: b"x"})
    server = serve(body)

    with pytest.raises(ValueError, match="refused"):
        install_music_v2(tmp_path / "lib" / "music-v2", url=server.url, sha256=_sha(body))

    assert not (tmp_path / "lib" / "music-v2").exists()
    assert not (tmp_path / "lib" / "escape.opus").exists()


def test_unpacking_refuses_links(serve, tmp_path: Path) -> None:
    def link(bundle: tarfile.TarFile) -> None:
        info = tarfile.TarInfo("music-v2/calm/evil.opus")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        bundle.addfile(info)

    body = _tar(_library_entries(), extra=link)
    server = serve(body)

    with pytest.raises(ValueError, match="non-file"):
        install_music_v2(tmp_path / "music-v2", url=server.url, sha256=_sha(body))


def test_an_archive_missing_a_mood_is_refused(serve, tmp_path: Path) -> None:
    entries = {k: v for k, v in _library_entries().items() if "/tender/" not in k}
    body = _tar(entries)
    server = serve(body)

    with pytest.raises(ValueError, match="tender"):
        install_music_v2(tmp_path / "music-v2", url=server.url, sha256=_sha(body))

    assert not (tmp_path / "music-v2").exists()


def test_the_directory_follows_the_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(MUSIC_DIR_ENV, str(tmp_path / "baked"))
    assert music_v2_dir() == tmp_path / "baked"
    monkeypatch.delenv(MUSIC_DIR_ENV)
    assert music_v2_dir() == Path.home() / ".immich-memories" / "models" / "music-v2"


def _installed_library(root: Path, *, moods=MUSIC_V2_MOODS, marker=MUSIC_V2.sha256) -> Path:
    for mood in moods:
        (root / mood).mkdir(parents=True)
        (root / mood / f"{mood}.opus").write_bytes(b"opus")
    if marker:
        (root / MARKER).write_text(marker)
    return root


def _package_tracks(monkeypatch, tmp_path: Path) -> Path:
    package = tmp_path / "package"
    (package / "calm").mkdir(parents=True)
    import sys
    import types

    module = types.ModuleType("immich_memories_music")
    module.tracks_dir = lambda: package  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "immich_memories_music", module)
    return package


def test_a_complete_v1_library_wins(monkeypatch, tmp_path: Path) -> None:
    v1 = _installed_library(tmp_path / "v1")
    _package_tracks(monkeypatch, tmp_path)
    monkeypatch.setenv(MUSIC_DIR_ENV, str(v1))

    assert bundled_music.bundled_library() == v1


@pytest.mark.parametrize(
    "build",
    [
        lambda _root: None,
        lambda root: _installed_library(root, moods=MUSIC_V2_MOODS[:3]),
        lambda root: _installed_library(root, marker="deadbeef"),
        lambda root: _installed_library(root, marker=""),
    ],
    ids=["missing", "incomplete", "wrong digest marker", "never verified"],
)
def test_an_unusable_v1_falls_back_to_the_package(monkeypatch, tmp_path: Path, build) -> None:
    v1 = tmp_path / "v1"
    build(v1)
    package = _package_tracks(monkeypatch, tmp_path)
    monkeypatch.setenv(MUSIC_DIR_ENV, str(v1))

    assert bundled_music.bundled_library() == package


def test_with_neither_there_is_no_library(monkeypatch, tmp_path: Path) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "immich_memories_music", None)
    monkeypatch.setenv(MUSIC_DIR_ENV, str(tmp_path / "absent"))

    assert bundled_music.bundled_library() is None


def test_finding_the_library_never_touches_the_network(monkeypatch, tmp_path: Path) -> None:
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("a film must not open a connection for music")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv(MUSIC_DIR_ENV, str(tmp_path / "absent"))
    _package_tracks(monkeypatch, tmp_path)

    assert bundled_music.bundled_library() is not None


def test_the_plan_fetches_music_unless_music_is_off() -> None:
    on = Config()
    off = Config()
    off.audio.no_music = True

    planned = [item for item in acquisition_plan(on) if item.artifact == MUSIC_V2]
    assert len(planned) == 1
    assert planned[0].unpack
    assert planned[0].destination == music_v2_dir()
    assert not [item for item in acquisition_plan(off) if item.artifact == MUSIC_V2]
