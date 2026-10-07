"""`runs upload`: send a finished run's film to Immich without rendering it again."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import click

from immich_memories.cli._helpers import print_error, print_success
from immich_memories.config_loader import Config


@contextmanager
def immich_client(config: Config) -> Iterator[Any]:
    from immich_memories.api.sync_client import SyncImmichClient

    with SyncImmichClient(
        base_url=config.immich.url,
        api_key=config.immich.api_key,
        api_version=config.immich.api_version,
    ) as client:
        yield client


def register_upload_command(runs: click.Group) -> None:
    """Add `runs upload` to the `runs` group."""

    @runs.command("upload")
    @click.argument("run_id")
    @click.option("--album", default=None, help="Immich album for the upload")
    def runs_upload(run_id: str, album: str | None) -> None:
        """Upload RUN_ID's finished film to Immich, as it is on disk.

        RUN_ID is the render run's id (`runs list` shows it; it ends the film's folder name):
        the run that holds the film, not the cut it was rendered from. Nothing is rendered again. The key
        needs the same upload scope the render-time option checks, and a cut never rendered
        or a film removed from disk is refused.
        """
        import httpx

        from immich_memories.api.immich import ImmichAPIError
        from immich_memories.config import get_config
        from immich_memories.web.run_upload import UploadRefused, upload_finished_film

        config = get_config()
        try:
            with immich_client(config) as client:
                uploaded = upload_finished_film(
                    config,
                    run_id,
                    album,
                    missing_upload=client.get_key_capabilities().missing_upload,
                    client=client,
                )
        except UploadRefused as refusal:
            print_error(str(refusal))
            sys.exit(1)
        except (ImmichAPIError, httpx.HTTPError) as error:
            print_error(f"Immich could not take the upload: {error}")
            sys.exit(1)
        suffix = f" into {uploaded.album}" if uploaded.album else ""
        print_success(f"Uploaded to Immich{suffix}: asset {uploaded.asset_id}", highlight=False)
        if uploaded.asset_url:
            click.echo(uploaded.asset_url)
