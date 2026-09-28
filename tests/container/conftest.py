"""The container suite: the image CI builds, started from `docker-compose.yml` on a legacy volume.

`make test-container` builds the image and names it in `IMMICH_MEMORIES_CONTAINER_IMAGE`;
`IMMICH_MEMORIES_CONTAINER_DATABASE` picks the store backend (sqlite or postgresql). One
deployment per session: the volume holds a pre-store `~/.immich-memories` before the new
image first starts on it, the way an upgrade finds it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.container.deployment import Deployment, copy_tree
from tests.store.legacy_home import write_legacy_home

IMAGE_ENV = "IMMICH_MEMORIES_CONTAINER_IMAGE"
DATABASE_ENV = "IMMICH_MEMORIES_CONTAINER_DATABASE"


@pytest.fixture(scope="session")
def deployment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Deployment]:
    """The app running from the compose file on a volume an older release left behind."""
    image = os.environ.get(IMAGE_ENV, "")
    backend = os.environ.get(DATABASE_ENV, "sqlite")
    if not image:
        pytest.fail(f"{IMAGE_ENV} is not set; run the suite through make test-container")
    if backend not in {"sqlite", "postgresql"}:
        pytest.fail(f"{DATABASE_ENV} must be sqlite or postgresql, got {backend!r}")

    root = tmp_path_factory.mktemp("container")
    # write_legacy_home puts owner edits beside the films, in <parent>/Videos/Memories.
    legacy = write_legacy_home(root / "legacy" / "home")
    deployment = Deployment(image=image, backend=backend, root=root / "project")
    deployment.write()
    copy_tree(root / "legacy" / "Videos" / "Memories", deployment.output_dir)
    try:
        deployment.seed_volume(legacy)
        deployment.up()
        yield deployment
    finally:
        deployment.down()


@pytest.fixture(scope="session")
def upgraded(deployment: Deployment) -> str:
    """`store status` once the first start has imported the legacy volume."""

    def imported() -> str | None:
        status = deployment.cli("store", "status")
        return status if "Import:    from" in status else None

    return deployment.wait_for(imported, "the first-open import of the legacy volume")
