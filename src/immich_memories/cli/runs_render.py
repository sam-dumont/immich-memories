"""`runs render`: render a saved cut, or one of its revisions, without selecting again.

It takes `generate`'s output flags under the same names and ends in the same engine
(`generate_saved_cut.render_saved_cut` → `generate_memory`), the road the web client's export
takes too. `generate --no-render` followed by `runs render` is a cut and its film in two steps.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import click

from immich_memories.cli._helpers import print_error, print_success
from immich_memories.cli._runs_reading import RunNotFound, resolve_attempt
from immich_memories.generate_saved_cut import CutRenderRequest, render_saved_cut
from immich_memories.operations.cut_revisions import read_revisions
from immich_memories.operations.revision_render import RenderUnavailable


def _write_progress(path: Path | None, record: dict) -> None:
    if path is None:
        return
    # Written whole and swapped in, so a reader never sees half a record.
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(record | {"updated_at": time.time()}))
    os.replace(temporary, path)


def _progress_writer(path: Path | None):
    def report(phase: str, fraction: float, message: str) -> None:
        _write_progress(
            path, {"done": False, "phase": phase, "fraction": fraction, "message": message}
        )

    return report if path is not None else None


def register_render_command(runs: click.Group) -> None:
    """Add `runs render` to the `runs` group."""

    @runs.command("render")
    @click.argument("run_id", required=False)
    @click.option(
        "--revision", type=int, default=None, help="Render this saved revision of the cut"
    )
    @click.option("--title", default=None, help="Title card text (default: as generate decides)")
    @click.option("--subtitle", default=None, help="Title card subtitle")
    @click.option("--llm-title/--no-llm-title", default=None, help="Let the model name the film")
    @click.option(
        "--transition", type=click.Choice(["smart", "crossfade", "cut", "none"]), default=None
    )
    @click.option("--resolution", default=None, help="Output resolution, as generate takes it")
    @click.option("--orientation", default=None, help="landscape, portrait, square or auto")
    @click.option("--scale-mode", default=None, help="How sources fit the canvas")
    @click.option("--format", "output_format", type=click.Choice(["mp4", "mov"]), default=None)
    @click.option("--music", type=click.Path(exists=True, path_type=Path), default=None)
    @click.option("--no-music", is_flag=True, default=False)
    @click.option("--music-volume", type=float, default=0.5, show_default=True)
    @click.option("--add-date", is_flag=True, default=False, help="Date overlay on each clip")
    @click.option("--add-place", is_flag=True, default=False, help="Place overlay on each clip")
    @click.option("--privacy-mode", is_flag=True, default=False)
    @click.option("--upload-to-immich", is_flag=True, default=False)
    @click.option("--album", default=None, help="Immich album for the upload")
    @click.option(
        "--progress-file",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Keep the render's progress in this JSON file, for a watcher such as the web client",
    )
    def runs_render(
        run_id: str | None, revision: int | None, progress_file: Path | None, **options
    ) -> None:
        """Render a finished cut, or one of its saved revisions, through the same engine as generate.

        With no RUN_ID the most recent completed run is rendered. Revisions are the ones the web
        client saved (`--revision 2`); without one, the cut renders as it was chosen.
        """
        from immich_memories.api.sync_client import SyncImmichClient
        from immich_memories.config import get_config
        from immich_memories.tracking import RunDatabase

        config = get_config()
        db = RunDatabase(db_path=config.cache.database_path)
        try:
            resolved, attempt = resolve_attempt(config.cache.cache_path, db, run_id)
        except RunNotFound as exc:
            print_error(str(exc))
            sys.exit(1)
        chosen = None
        if revision is not None:
            chosen = next((r for r in read_revisions(attempt) if r.number == revision), None)
            if chosen is None:
                print_error(f"Run {resolved} has no revision {revision}.")
                sys.exit(1)
        request = CutRenderRequest(
            title=options["title"],
            subtitle=options["subtitle"],
            llm_title=options["llm_title"],
            transition=options["transition"],
            output_resolution=options["resolution"],
            output_orientation=options["orientation"],
            scale_mode=options["scale_mode"],
            output_format=options["output_format"],
            add_date_overlay=options["add_date"],
            add_place_overlay=options["add_place"],
            privacy_mode=options["privacy_mode"],
            music_path=options["music"],
            music_volume=options["music_volume"],
            no_music=options["no_music"],
            upload=options["upload_to_immich"],
            album=options["album"],
        )
        run = db.get_run(resolved)
        if run is None:
            print_error(f"Run {resolved} is not in the run database.")
            sys.exit(1)
        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            try:
                path = render_saved_cut(
                    config=config,
                    client=client,
                    run=run,
                    attempt_dir=attempt,
                    revision=chosen,
                    request=request,
                    progress_callback=_progress_writer(progress_file),
                )
            except (RenderUnavailable, ValueError) as exc:
                print_error(str(exc))
                sys.exit(1)
        _write_progress(progress_file, {"done": True, "fraction": 1.0, "output_path": str(path)})
        print_success(f"Rendered {path}")
