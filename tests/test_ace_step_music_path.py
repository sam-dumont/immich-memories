"""Which source a film's music takes: the decision table behind generating only from XL."""

from __future__ import annotations

import httpx
import pytest

from immich_memories.audio.generators import ace_step_music_path as path_module
from immich_memories.audio.generators.ace_step_model_choice import HostMemory
from immich_memories.audio.generators.ace_step_music_path import decide_music_path, server_model

_REQUEST = httpx.Request("GET", "http://ace.invalid/health")
BIG_MAC = HostMemory(unified_gib=64.0)
SMALL_MAC = HostMemory(unified_gib=32.0)
BIG_GPU = HostMemory(gpu_gib=16.0)
SMALL_GPU = HostMemory(gpu_gib=8.0)
NO_GPU = HostMemory()


@pytest.mark.parametrize(
    ("host", "generates"),
    [(BIG_MAC, True), (BIG_GPU, True), (SMALL_MAC, False), (SMALL_GPU, False), (NO_GPU, False)],
)
def test_local_auto_generates_only_where_xl_fits(host, generates):
    result = decide_music_path(mode="lib", configured="auto", host=host, server_model=None)

    assert result.generate is generates
    assert bool(result.reason) is (not generates)
    assert result.notice is None


def test_a_small_host_explains_why_it_uses_the_library():
    result = decide_music_path(mode="lib", configured="auto", host=SMALL_MAC, server_model=None)

    assert "32 GB" in result.reason and "bundled library" in result.reason


@pytest.mark.parametrize("variant", ["xl-turbo", "acestep-v15-xl-turbo", "xl-base"])
def test_a_written_xl_variant_is_used_as_written_even_on_a_small_host(variant):
    result = decide_music_path(mode="lib", configured=variant, host=SMALL_MAC, server_model=None)

    assert result.generate and result.notice is None


@pytest.mark.parametrize("variant", ["turbo", "base"])
def test_a_written_2b_variant_still_generates_with_a_notice_naming_the_way_out(variant):
    result = decide_music_path(mode="lib", configured=variant, host=BIG_MAC, server_model=None)

    assert result.generate
    assert result.notice and "auto" in result.notice and "xl-turbo" in result.notice
    assert "bundled library" in result.notice


@pytest.mark.parametrize(
    ("server", "generates"),
    [
        ("acestep-v15-xl-turbo", True),
        ("acestep-v15-xl-base", True),
        ("acestep-v15-turbo", False),
        ("acestep-v15-base", False),
        (None, False),
    ],
)
def test_api_generates_only_when_the_server_runs_xl(server, generates):
    result = decide_music_path(mode="api", configured="auto", host=NO_GPU, server_model=server)

    assert result.generate is generates
    assert bool(result.reason) is (not generates)


def test_an_unknown_server_model_says_how_to_assert_xl():
    result = decide_music_path(mode="api", configured="auto", host=NO_GPU, server_model=None)

    assert "could not learn" in result.reason and "xl-turbo" in result.reason


def test_the_owner_can_state_that_the_server_runs_xl():
    result = decide_music_path(mode="api", configured="xl-turbo", host=NO_GPU, server_model=None)

    assert result.generate


def test_the_server_model_is_read_from_health(monkeypatch):
    body = {"data": {"status": "ok", "loaded_model": "acestep-v15-xl-turbo"}, "code": 200}
    monkeypatch.setattr(  # WHY: the ACE-Step server is the network boundary
        path_module.httpx,
        "get",
        lambda _url, **_kw: httpx.Response(200, json=body, request=_REQUEST),
    )

    assert server_model("http://ace:8000/") == "acestep-v15-xl-turbo"


@pytest.mark.parametrize("body", [{"data": {"status": "ok"}}, {"data": {"loaded_model": None}}, []])
def test_a_health_without_a_loaded_model_is_unknown(monkeypatch, body):
    monkeypatch.setattr(  # WHY: the ACE-Step server is the network boundary
        path_module.httpx,
        "get",
        lambda _url, **_kw: httpx.Response(200, json=body, request=_REQUEST),
    )

    assert server_model("http://ace:8000") is None


def test_an_unreachable_server_is_unknown(monkeypatch):
    def refuse(_url, **_kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(path_module.httpx, "get", refuse)  # WHY: the network boundary
    monkeypatch.setattr(path_module.time, "sleep", lambda _s: None)  # WHY: no real waiting

    assert server_model("http://ace:8000") is None


def test_one_dropped_probe_does_not_make_the_server_unknown(monkeypatch):
    answers = [
        httpx.ReadError("eof"),
        httpx.Response(
            200,
            json={"data": {"loaded_model": "acestep-v15-xl-turbo"}},
            request=_REQUEST,
        ),
    ]

    def flaky(_url, **_kw):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(path_module.httpx, "get", flaky)  # WHY: the network boundary
    monkeypatch.setattr(path_module.time, "sleep", lambda _s: None)  # WHY: no real waiting

    assert server_model("http://ace:8000") == "acestep-v15-xl-turbo"
