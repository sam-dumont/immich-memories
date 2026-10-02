"""`runs render`: render a saved cut, or one of its revisions, without selecting again.

It takes `generate`'s output flags under the same names and ends in the same engine
(`generate_saved_cut.render_saved_cut` → `generate_memory`), the road the web client's export
takes too. `generate --no-render` followed by `runs render` is a cut and its film in two steps.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from immich_memories.cli._helpers import print_error, print_success
from immich_memories.cli._runs_reading import RunNotFound, resolve_attempt
from immich_memories.cli.progress_file import progress_writer, write_progress
from immich_memories.generate_saved_cut import CutRenderRequest, render_saved_cut
from immich_memories.operations.cut_revisions import read_revisions
from immich_memories.operations.revision_render import RenderUnavailable


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
        "--transition",
        type=click.Choice(["smart", "crossfade", "cut", "none"]),
        default=None,
        help="Transition style (default: saved cut)",
    )
    @click.option(
        "--fade-color",
        type=click.Choice(["white", "black"]),
        default=None,
        help="Opening and closing title fade (default: title_screens.fade_color)",
    )
    @click.option(
        "--resolution",
        type=click.Choice(["auto", "4k", "1080p", "720p"]),
        default=None,
        help="Output resolution (default: from config)",
    )
    @click.option(
        "--orientation",
        type=click.Choice(["landscape", "portrait", "square", "auto"]),
        default=None,
        help="Output orientation (default: auto, follows the saved cut)",
    )
    @click.option(
        "--scale-mode",
        type=click.Choice(["fit", "blur"]),
        default=None,
        help="Fill an aspect mismatch with black bars or a blurred background",
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["mp4", "h265", "prores"]),
        default=None,
        help="Output format override, as generate takes it (default: config value)",
    )
    @click.option(
        "--quality",
        type=click.Choice(["high", "medium", "low"]),
        default=None,
        help="Output quality: high, medium (balanced), low (fast); default: from config",
    )
    @click.option("--music", default=None, help="A track to use, or 'auto' to choose as configured")
    @click.option("--no-music", is_flag=True, default=False, help="Render without a music track")
    @click.option(
        "--music-volume",
        type=float,
        default=0.5,
        show_default=True,
        help="Music volume from 0.0 to 1.0",
    )
    @click.option(
        "--add-date/--no-add-date",
        default=None,
        help="Caption each clip with its date (default: defaults.add_date, on)",
    )
    @click.option(
        "--add-place/--no-add-place",
        default=None,
        help="Caption each clip with its place (default: defaults.add_place, on)",
    )
    @click.option(
        "--privacy-mode",
        is_flag=True,
        default=False,
        help="Demo mode: blur every clip frame, scramble the audio, fake the person names",
    )
    @click.option(
        "--upload-to-immich",
        is_flag=True,
        default=False,
        help="Upload the film to Immich after rendering",
    )
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
        from immich_memories.api.access_clients import AccessBoundClient
        from immich_memories.config import get_config
        from immich_memories.db import open_store
        from immich_memories.tracking import RunDatabase

        config = get_config()
        db = RunDatabase(open_store(config))
        try:
            resolved, attempt = resolve_attempt(db, run_id)
        except RunNotFound as exc:
            print_error(str(exc))
            sys.exit(1)
        chosen = None
        if revision is not None:
            chosen = next((r for r in read_revisions(attempt) if r.number == revision), None)
            if chosen is None:
                print_error(f"Run {resolved} has no revision {revision}.")
                sys.exit(1)
        from immich_memories.generate_captions import resolve_caption_overlays

        add_date, add_place = resolve_caption_overlays(
            config, add_date=options["add_date"], add_place=options["add_place"]
        )
        request = CutRenderRequest(
            title=options["title"],
            subtitle=options["subtitle"],
            llm_title=options["llm_title"],
            transition=options["transition"],
            fade_color=options["fade_color"],
            output_resolution=options["resolution"],
            output_orientation=options["orientation"],
            scale_mode=options["scale_mode"],
            output_format=options["output_format"],
            quality=options["quality"],
            add_date_overlay=add_date,
            add_place_overlay=add_place,
            privacy_mode=options["privacy_mode"],
            # "auto" is a request to choose, as generate reads it, not a file to load.
            music_path=Path(options["music"]) if options["music"] not in {None, "auto"} else None,
            music_volume=options["music_volume"],
            no_music=options["no_music"],
            upload=options["upload_to_immich"],
            album=options["album"],
        )
        run = db.get_run(resolved)
        if run is None:
            print_error(f"Run {resolved} is not in the run database.")
            sys.exit(1)
        with AccessBoundClient(config.immich) as client:
            try:
                path = render_saved_cut(
                    config=config,
                    client=client,
                    run=run,
                    attempt_dir=attempt,
                    revision=chosen,
                    request=request,
                    progress_callback=progress_writer(progress_file),
                )
            except (RenderUnavailable, ValueError) as exc:
                print_error(str(exc))
                sys.exit(1)
        write_progress(progress_file, {"done": True, "fraction": 1.0, "output_path": str(path)})
        print_success(f"Rendered {path}")
