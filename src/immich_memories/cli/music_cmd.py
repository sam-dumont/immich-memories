"""Music commands for Immich Memories CLI."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from immich_memories.cli._helpers import console, print_error, print_success


def register_music_commands(main: click.Group) -> None:
    """Register the music command group on the main CLI group."""

    @main.group()
    def music() -> None:
        """Music and audio commands."""
        pass

    main.add_command(music)
    _register_preview(music)

    @music.command("search")
    @click.option("--mood", "-m", type=str, help="Mood (happy, calm, energetic, etc.)")
    @click.option("--genre", "-g", type=str, help="Genre (acoustic, electronic, cinematic, etc.)")
    @click.option("--tempo", "-t", type=click.Choice(["slow", "medium", "fast"]), help="Tempo")
    @click.option("--min-duration", type=float, default=60, help="Minimum duration in seconds")
    @click.option("--limit", "-n", type=int, default=10, help="Number of results")
    @click.pass_context
    def music_search(
        ctx: click.Context,
        mood: str | None,
        genre: str | None,
        tempo: str | None,
        min_duration: float,
        limit: int,
    ) -> None:
        """Search for music in local library."""
        import asyncio

        from immich_memories.audio.music_sources import LocalMusicSource
        from immich_memories.config import Config

        async def search():
            config = Config.from_yaml(Config.get_default_path())
            source = LocalMusicSource(music_dir=config.audio.local_music_path)
            return await source.search(
                mood=mood,
                genre=genre,
                tempo=tempo,
                min_duration=min_duration,
                limit=limit,
            )

        console.print("[bold]Searching for music...[/bold]")
        console.print()

        if mood:
            console.print(f"Mood: {mood}")
        if genre:
            console.print(f"Genre: {genre}")
        if tempo:
            console.print(f"Tempo: {tempo}")
        console.print()

        tracks = asyncio.run(search())

        if not tracks:
            print_error("No tracks found matching criteria")
            return

        table = Table(title=f"Found {len(tracks)} tracks")
        table.add_column("Title", style="cyan")
        table.add_column("Artist", style="green")
        table.add_column("Duration", style="yellow")
        table.add_column("Tags")

        for track in tracks:
            duration = f"{int(track.duration_seconds // 60)}:{int(track.duration_seconds % 60):02d}"
            tags = ", ".join(track.tags[:3]) if track.tags else ""
            table.add_row(track.title, track.artist, duration, tags)

        console.print(table)

    @music.command("add")
    @click.argument("video_path", type=click.Path(exists=True))
    @click.argument("output_path", type=click.Path())
    @click.option(
        "--music",
        "-m",
        type=click.Path(exists=True),
        help="Music file (auto-select if not provided)",
    )
    @click.option("--mood", type=str, help="Override mood for music selection")
    @click.option("--genre", "-g", type=str, help="Override genre for music selection")
    @click.option("--volume", "-v", type=float, default=-6.0, help="Music volume in dB")
    @click.option("--fade-in", type=float, default=2.0, help="Fade in duration in seconds")
    @click.option("--fade-out", type=float, default=3.0, help="Fade out duration in seconds")
    @click.pass_context
    def music_add(
        ctx: click.Context,
        video_path: str,
        output_path: str,
        music: str | None,
        mood: str | None,
        genre: str | None,
        volume: float,
        fade_in: float,
        fade_out: float,
    ) -> None:
        """Add background music to a video with automatic ducking.

        Without a music file, picks a track from your library by --mood (calm when
        absent). No frame of the video is sent to any model.
        Music volume is automatically lowered when speech/sounds are detected.
        """
        import asyncio

        from immich_memories.audio.mixer_class import AudioMixer

        config = ctx.obj["config"]

        async def add_music():
            # WHY: auto-select must search the user's configured library, not a hidden cache dir
            mixer = AudioMixer(cache_dir=config.audio.local_music_path)
            return await mixer.add_music_to_video(
                video_path=Path(video_path),
                output_path=Path(output_path),
                music_path=Path(music) if music else None,
                mood=mood,
                genre=genre,
                fade_in=fade_in,
                fade_out=fade_out,
                music_volume_db=volume,
                auto_select=music is None,
            )

        console.print("[bold]Adding Music to Video[/bold]")
        console.print()
        console.print(f"Input: {video_path}")
        console.print(f"Output: {output_path}")
        if music:
            console.print(f"Music: {music}")
        else:
            console.print(f"Music: [dim]Auto-select, mood {mood or 'calm'}[/dim]")
        console.print()

        from rich.progress import Progress, SpinnerColumn, TextColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Processing...", total=None)

            try:
                result = asyncio.run(add_music())
                progress.update(task, completed=True)
            except Exception as e:  # WHY: CLI error display boundary
                print_error(f"Failed: {e}")
                return

        print_success(f"Video saved to: {result}")


def _register_preview(music: click.Group) -> None:
    @music.command("preview")
    @click.argument("run_id", required=False)
    @click.option(
        "--out",
        "out_dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Where to write the track (default: the cache, beside the run)",
    )
    @click.option(
        "--progress-file",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Keep generation progress in this JSON file, for a watcher such as the web client",
    )
    def music_preview(run_id: str | None, out_dir: Path | None, progress_file: Path | None) -> None:
        """Generate the music this cut would get, from its own timeline and mood, before rendering.

        The track it prints renders with `runs render RUN --music PATH`.
        """
        import asyncio
        import sys

        from immich_memories.audio.cut_music_preview import (
            PreviewUnavailable,
            preview_music_for_cut,
        )
        from immich_memories.cli._runs_reading import RunNotFound, resolve_attempt
        from immich_memories.cli.progress_file import write_progress
        from immich_memories.config import get_config
        from immich_memories.tracking import RunDatabase

        config = get_config()
        try:
            resolved, attempt = resolve_attempt(
                config.cache.cache_path, RunDatabase(db_path=config.cache.database_path), run_id
            )
        except RunNotFound as exc:
            print_error(str(exc))
            sys.exit(1)

        def progress(_version: int, status: str, percent: float, _detail: str) -> None:
            write_progress(
                progress_file,
                {"done": False, "phase": "music", "fraction": percent / 100, "message": status},
            )

        target = out_dir or config.cache.cache_path / "music-previews" / resolved
        try:
            track = asyncio.run(preview_music_for_cut(config, attempt, target, progress))
        except PreviewUnavailable as exc:
            print_error(str(exc))
            sys.exit(1)
        write_progress(progress_file, {"done": True, "fraction": 1.0, "output_path": str(track)})
        print_success(f"Music preview: {track}")
