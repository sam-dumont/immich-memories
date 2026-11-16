"""What a trace carries out of the house: no names, free text or home paths unless asked for.

Every span here goes through the real exporter to a local receiver, so the assertions read what
a collector would get. Content capture is the GenAI switch
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`); with it off, the values of the flags that
carry names or free text are replaced, and with it on they go out as given.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import click
import pytest
from opentelemetry.trace import Status, StatusCode

from immich_memories import logging_config
from immich_memories.tracking import otel, timing, trace_redaction
from immich_memories.tracking.timed import timed
from tests.otel_receiver import receiving

_CAPTURE = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
_HOME = "/Users/someone/.immich-memories"
_RENDER_ARGUMENTS = [
    "--person=Alex Example",
    "--person",
    "Sam Placeholder",
    "--ask=a film of Alex at the beach",
    "--title=Alex turns 5",
    "--album",
    "Holidays in Placeholder Town",
    f"--music={_HOME}/cache/music/preview-x.mp3",
    "--memory-key=person_monthly:2024-01-01:2024-01-31:alex example",
    "--resolution=1080p",
    "-vf",
    "drawtext=text='Placeholder Town':x=10:y=20",
    "--api-key=placeholder-key",
]
_PRIVATE_TEXT = (
    "Alex",
    "Sam Placeholder",
    "beach",
    "Placeholder Town",
    "alex example",
    "/Users/someone",
    "placeholder-key",
)


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.delenv(_CAPTURE, raising=False)
    with receiving(monkeypatch) as received:
        otel.setup()
        yield received


def _program_arguments(collector) -> list[str]:
    with timing.span("render.assembly"):
        subprocess.run([sys.executable, "-c", "pass", *_RENDER_ARGUMENTS], check=True)
    span = next(span for span in collector.spans() if span["name"].startswith("exec "))
    return span["attributes"]["process.command_args"]


def test_program_arguments_lose_names_free_text_and_home_paths(collector):
    arguments = _program_arguments(collector)

    assert arguments[3:] == [
        "--person={redacted}",
        "--person",
        "{redacted}",
        "--ask={redacted}",
        "--title={redacted}",
        "--album",
        "{redacted}",
        "--music=preview-x.mp3",
        "--memory-key={redacted}",
        "--resolution=1080p",
        "-vf",
        "drawtext=text='{redacted}':x=10:y=20",
        "--api-key={redacted}",
    ]
    for text in _PRIVATE_TEXT:
        assert text not in repr(arguments)


def test_with_content_capture_on_the_names_and_free_text_go_out(collector, monkeypatch):
    monkeypatch.setenv(_CAPTURE, "true")

    arguments = _program_arguments(collector)

    assert "--person=Alex Example" in arguments
    assert arguments[4:6] == ["--person", "Sam Placeholder"]
    assert "--ask=a film of Alex at the beach" in arguments
    assert "--title=Alex turns 5" in arguments
    assert "drawtext=text='Placeholder Town':x=10:y=20" in arguments
    # A home path and a key are never content: they are cut either way.
    assert "--music=preview-x.mp3" in arguments
    assert "--api-key={redacted}" in arguments


def test_every_cli_option_that_takes_free_text_is_classified():
    """A new text option names its kind here, so it cannot reach a trace unclassified."""
    from immich_memories.cli import main

    # Ids, dates, periods, keys the app made up and settings that are not about anyone.
    plain = {
        "--also-skip", "--asset", "--automation-attempt-id", "--end", "--event-id", "--exclude",
        "--genre", "--head", "--host", "--id", "--include", "--memory-category", "--mood",
        "--music", "--near-date", "--period", "--run", "--schema", "--start", "--to", "--type",
        "--url", "--wrong", "-g", "-h", "-m", "-u",
    }  # fmt: skip
    text_options = set()
    commands = [main]
    while commands:
        command = commands.pop()
        commands.extend(getattr(command, "commands", {}).values())
        text_options.update(
            option
            for parameter in command.params
            if isinstance(parameter, click.Option)
            and isinstance(parameter.type, click.types.StringParamType)
            and not parameter.is_flag
            for option in parameter.opts
        )

    hidden = trace_redaction.PRIVATE_FLAGS | trace_redaction.SECRET_FLAGS
    assert text_options - plain - hidden == set()
    assert not plain & hidden


def test_a_list_attribute_holding_a_path_is_cut(collector):
    otel.end(otel.start("probe", {"inputs": [f"{_HOME}/cache/clip.mp4", "plain"]}))

    span = collector.named()["probe"]
    assert span["attributes"]["inputs"] == ["clip.mp4", "plain"]


class _Tiles(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def test_a_map_tile_request_keeps_no_coordinates(collector):
    import httpx

    server = HTTPServer(("127.0.0.1", 0), _Tiles)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with timing.span("titles.map"):
            httpx.get(f"http://127.0.0.1:{server.server_port}/tiles/14/8392/5467@2x.png")
    finally:
        server.shutdown()
        server.server_close()

    call = next(span for span in collector.spans() if span["kind"] == 3)
    assert call["name"] == "GET /tiles/{id}/{id}/{id}@2x.png"
    assert call["attributes"]["url.full"].endswith("/tiles/{id}/{id}/{id}@2x.png")
    # The ids are random hex and can hold these digits by chance: look at what the span says.
    said = {
        key: value for key, value in call.items() if key not in {"trace_id", "span_id", "parent"}
    }
    assert "8392" not in repr(said)


def test_a_route_segment_that_names_someone_is_templated(collector):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/api/v1/accounts/{name}/people")
    def people(name: str) -> list[str]:
        return []

    otel.instrument_app(app)
    with TestClient(app) as client:
        client.get("/api/v1/accounts/Alex Example/people")

    route = next(span for span in collector.spans() if span["kind"] == 2)
    assert route["attributes"]["url.path"] == "/api/v1/accounts/{name}/people"
    assert "Alex" not in repr(route)


def test_an_exception_a_route_raised_arrives_scrubbed_with_the_app_frames_only(
    collector, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # WHY: the redaction list is module state; the test's own secret must not outlive it.
    monkeypatch.setattr(logging_config, "_secret_values", ())
    logging_config.install_secret_redaction(["lab-secret-value"])
    app = FastAPI()

    # The app's own frame on the way: the decorator that measures the read.
    @timed("film.read")
    def read() -> None:
        raise OSError(f"could not open {_HOME}/store.db with lab-secret-value")

    @app.get("/api/v1/films/{film_id}")
    def film(film_id: str) -> None:
        read()

    otel.instrument_app(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/api/v1/films/one")

    route = next(span for span in collector.spans() if span["kind"] == 2)
    (exception,) = [attributes for name, attributes in route["events"] if name == "exception"]
    assert exception["exception.message"] == "could not open store.db with [redacted]"
    frames = exception["exception.stacktrace"].splitlines()
    assert frames
    assert all(frame.startswith("tracking/timed.py:") for frame in frames)
    assert "lab-secret-value" not in repr(route)
    assert "/Users/" not in repr(route)
    assert "site-packages" not in repr(route)


def test_a_status_description_with_a_path_is_cut(collector):
    span = otel.start("probe")
    span.set_status(Status(StatusCode.ERROR, f"could not open {_HOME}/store.db"))
    otel.end(span)

    assert collector.named()["probe"]["status_message"] == "could not open store.db"
