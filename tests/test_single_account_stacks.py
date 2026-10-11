"""A one-account run folds Immich stacks too, not only a household (#2351).

The source step of a default `generate` runs over the real client and the fake Immich of
`tests/test_access_bound_reads.py`, which here also answers `GET /stacks`: an edit and its
original stacked, the star on the original.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from immich_memories.analysis.editorial_pool import discover_source_context, resolve_source_pool
from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_source import library_source_scope
from immich_memories.analysis.selection_source import prepare_editorial_source
from immich_memories.api.sync_client import SyncImmichClient
from tests.test_access_bound_reads import (
    PRIMARY_KEY,
    URL,
    WINDOW,
    _asset,
    _config,
    immich,  # noqa: F401 - the fake Immich fixture
)


def _cut_sources(tmp_path) -> dict:
    """The candidates a default single-account cut hands its editor."""
    config = _config(tmp_path)
    context = EditorialRunContext(
        key="one-account",
        label="June",
        product="month",
        date_ranges=(WINDOW,),
        target_seconds=60,
        artifact_dir=tmp_path / "attempt",
    )
    # The client `cli/run_people.py::run_client` builds when no account is named.
    with SyncImmichClient(base_url=URL, api_key=PRIMARY_KEY, api_version="v2") as client:
        planner = build_editorial_planner(
            source_pool=resolve_source_pool(
                client,
                discover_source_context(
                    client, library_source_scope(client, config, context.date_ranges)
                ),
            ),
            client=client,
            thumbnail_cache=object(),
            context=context,
            config=config,
            ports=EditorialRuntimePorts(load_people=lambda: {}),
        )._planner
        prepared = prepare_editorial_source(
            planner._selection_request,
            replace(planner._source_dependencies, preview_jpeg=None),
            group=False,
        )
    return {candidate.asset_id: candidate.source for candidate in prepared.candidates}


def _serve_stacks(monkeypatch, answer: httpx.Response) -> None:
    """Add `GET /stacks` to the fake server's answers."""
    fake_client = httpx.AsyncClient

    def client_with_stacks(**kwargs):
        serve = fake_client(**kwargs)._transport.handler  # type: ignore[attr-defined]

        def handler(request):
            return answer if request.url.path == "/api/stacks" else serve(request)

        return httpx._client.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    # WHY: the Immich HTTP boundary; the fake server, answering one more endpoint.
    monkeypatch.setattr(httpx, "AsyncClient", client_with_stacks)


@pytest.fixture
def stacked(immich):  # noqa: F811
    """The edit is the stack's primary; the starred original is its member."""
    immich.hold(PRIMARY_KEY, _asset("edit", "user-primary", bytes_of="edit"))
    immich.hold(PRIMARY_KEY, _asset("original", "user-primary", bytes_of="raw", favourite=True))
    return immich


def test_a_one_account_cut_keeps_one_picture_of_a_stack_with_the_members_star(
    tmp_path, stacked, monkeypatch
):
    stack = {"id": "s1", "primaryAssetId": "edit", "assets": [{"id": "edit"}, {"id": "original"}]}
    _serve_stacks(monkeypatch, httpx.Response(200, json=[stack]))

    sources = _cut_sources(tmp_path)

    assert set(sources) == {"edit"}
    assert sources["edit"].is_favorite


def test_a_key_without_stack_read_still_cuts_every_picture(tmp_path, stacked, monkeypatch):
    _serve_stacks(monkeypatch, httpx.Response(403, json={"message": "Missing stack.read"}))

    assert set(_cut_sources(tmp_path)) == {"edit", "original"}
