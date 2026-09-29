"""An account that cannot read its owner's picture fails the run; a broken file does not (#1500).

Preparation turns one picture it cannot use into unavailable evidence and carries on. That
is right for a corrupt preview and wrong for a household account whose reads fail: the
film would pass for complete with an owner missing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from immich_memories.analysis.editorial_demanded_previews import DemandedPreviewReader
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.api.access_clients import AccessBoundClient, AccountReadFailed
from immich_memories.api.models import Asset
from immich_memories.cache.thumbnail_cache import ThumbnailCache
from tests.test_access_bound_reads import (
    PARTNER_KEY,
    PRIMARY_KEY,
    _asset,
    _config,
    immich,  # noqa: F401 - the fake Immich fixture
)


@pytest.fixture
def previews(tmp_path, immich):  # noqa: F811
    """The planner's demanded preview reader over a household run's client."""
    immich.hold(PRIMARY_KEY, _asset("own-photo", "user-primary"))
    immich.hold(PARTNER_KEY, _asset("partner-photo", "user-partner"))
    client = AccessBoundClient(_config(tmp_path).immich)
    client.routes.learn(
        Asset.model_validate(_asset(asset_id, owner)).model_copy(
            update={"access_accounts": (account,)}
        )
        for asset_id, owner, account in (
            ("own-photo", "user-primary", "primary"),
            ("partner-photo", "user-partner", "partner"),
        )
    )
    reader = DemandedPreviewReader(
        ThumbnailCache(tmp_path / "thumbnails"),
        lambda asset_id: EditorialRuntimePorts().fetch_preview(client, asset_id),
        allowed_ids={"own-photo", "partner-photo"},
    )
    yield reader
    client.close()


def test_a_partner_preview_the_partner_cannot_read_fails_the_run_naming_it(
    immich,  # noqa: F811
    previews,
):
    immich.revoked.add(PARTNER_KEY)

    with pytest.raises(AccountReadFailed, match="'partner' could not read asset partner-photo"):
        previews("partner-photo")


def test_a_preview_that_is_not_a_picture_is_only_that_picture_unavailable(previews):
    # The fake serves text, not a JPEG: a broken file, read fine by its own account.
    assert previews("own-photo") is None
    assert previews.metrics()["unavailable"] == 1


SRC = Path(__file__).resolve().parents[1] / "src" / "immich_memories"
# The per-picture handlers of preparation and selection: each turns one unusable picture
# into unavailable evidence, so each must let an account's failed read through first.
# Not the detectors worker: it runs in a detector-only interpreter over previews already on
# disk, reads nothing from Immich, and must not import the package at all.
UNGUARDED = {SRC / "analysis/editorial_preparation_detectors.py"}
GUARDED = sorted(
    {
        *SRC.glob("analysis/editorial_preparation*.py"),
        *SRC.glob("analysis/selection_source*.py"),
        SRC / "analysis/editorial_demanded_previews.py",
        SRC / "speech/facts.py",
    }
    - UNGUARDED
)


def _catches_everything(handler: ast.ExceptHandler) -> bool:
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        kind is None or (isinstance(kind, ast.Name) and kind.id in {"Exception", "BaseException"})
        for kind in kinds
    )


def _lets_account_reads_through(handler: ast.ExceptHandler) -> bool:
    return (
        isinstance(handler.type, ast.Name)
        and handler.type.id == "AccountReadFailed"
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Raise)
        and handler.body[0].exc is None
    )


def _swallowing_handlers(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if not isinstance(node, ast.Try | ast.TryStar):
            continue
        for index, handler in enumerate(node.handlers):
            # A handler that ends in a bare `raise` already hands every failure on.
            last = handler.body[-1]
            re_raises = isinstance(last, ast.Raise) and last.exc is None
            if not _catches_everything(handler) or re_raises:
                continue
            if not any(_lets_account_reads_through(h) for h in node.handlers[:index]):
                found.append(f"{path.relative_to(SRC)}:{handler.lineno}")
    return found


def test_every_broad_handler_in_preparation_and_selection_lets_account_reads_through():
    swallowing = [site for path in GUARDED for site in _swallowing_handlers(path)]

    assert len(GUARDED) > 5
    assert swallowing == [], (
        "add `except AccountReadFailed: raise` before these broad handlers: "
        + ", ".join(swallowing)
    )
