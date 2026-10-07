"""`preflight` prints its table, not the HTTP client's request lines above it."""

import logging
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.cli import main

REQUEST_LINE = "HTTP Request: GET http://immich/api/server/ping"


@pytest.fixture(autouse=True)
def _restore_httpx_level():
    before = logging.getLogger("httpx").level
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    yield
    logging.getLogger("httpx").setLevel(before)


def _checks_that_call_a_server(_config):
    logging.getLogger("httpx").info(f'{REQUEST_LINE} "HTTP/1.1 200 OK"')
    return []


def _preflight_output(*group_args):
    runner = CliRunner()
    with (
        patch("immich_memories.cli.init_config_dir"),
        # WHY: the real checks reach an Immich server; the log line they cause is the subject.
        patch("immich_memories.preflight.run_preflight_checks", _checks_that_call_a_server),
        runner.isolated_filesystem() as cwd,
    ):
        path = f"{cwd}/c.yaml"
        with open(path, "w") as handle:
            handle.write("immich:\n  url: http://immich\n  api_key: k\n")
        return runner.invoke(main, ["-c", path, *group_args, "preflight"]).output


def test_the_default_preflight_hides_http_request_lines():
    assert REQUEST_LINE not in _preflight_output()


def test_a_verbose_run_keeps_them():
    assert REQUEST_LINE in _preflight_output("-v")
