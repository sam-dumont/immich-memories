"""Config and connection commands for Immich Memories CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.markup import escape
from rich.table import Table

from immich_memories.cli._helpers import console, print_error, print_info, print_success
from immich_memories.config import Config


def _config_file(ctx: click.Context) -> Path:
    """The config.yaml this run reads: `--config PATH` when given, else the default path."""
    return ctx.obj.get("config_path") or Config.get_default_path()


def _prompt_for_api_key(existing: str) -> str:
    """Ask for an API key without ever showing the one already configured.

    `hide_input` hides what is typed, not the default, so Click renders
    `API key [sk-live-...]:` -- and that key has full library access, so the line
    reaches the terminal, scrollback and any recording. Nothing is shown; an
    empty answer keeps the existing key, and the notice keeps an empty prompt
    from looking like an empty setting.
    """
    if existing:
        console.print("[dim]An API key is already configured — press enter to keep it.[/dim]")
    entered = click.prompt("API key", default="", hide_input=True, show_default=False)
    return entered or existing


def _save(ctx: click.Context, changes: dict[str, str]) -> bool:
    """Save to the database; print why not when env or config.yaml overrides a key."""
    from immich_memories.settings_edit import SettingRefused, save_settings

    cfg = ctx.obj["config"]
    changed = {key: value for key, value in changes.items() if _current(cfg, key) != value}
    if not changed:
        print_info("Nothing changed.")
        return True
    try:
        ctx.obj["config"] = save_settings(changed, path=_config_file(ctx))
    except SettingRefused as refusal:
        print_error(str(refusal))
        return False
    print_success(f"Saved to the database: {', '.join(sorted(changed))}")
    return True


def _current(cfg: Config, key: str) -> object:
    section, field = key.split(".")
    return getattr(getattr(cfg, section), field)


def _shown(value: object) -> str:
    if value == "":
        return "(not set)"
    return value if isinstance(value, str) else json.dumps(value)


def _show(ctx: click.Context, prefixes: tuple[str, ...]) -> None:
    from immich_memories.config_sources import describe_settings
    from immich_memories.settings_store import SECRET_KEY_ENV, secret_key_from_env

    config_path = _config_file(ctx)
    table = Table(title="Settings (env > config.yaml > database > default)")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green", overflow="fold")
    table.add_column("Source")
    table.add_column("Set by", style="dim", overflow="fold")
    for entry in describe_settings(ctx.obj["config"], path=config_path):
        if prefixes and not any(
            entry.key == prefix or entry.key.startswith(f"{prefix}.") for prefix in prefixes
        ):
            continue
        table.add_row(entry.key, escape(_shown(entry.value)), entry.source, entry.override or "")
    console.print(f"Config file: {config_path}")
    console.print(
        f"{SECRET_KEY_ENV}: {'set' if secret_key_from_env() else 'not set (secrets cannot be saved)'}"
    )
    console.print(table)


def _configure(ctx: click.Context, url: str | None, api_key: str | None) -> None:
    cfg = ctx.obj["config"]
    if url or api_key:
        changes = {"immich.url": url, "immich.api_key": api_key}
        if not _save(ctx, {key: value for key, value in changes.items() if value}):
            ctx.exit(1)
        return

    console.print("[bold]Immich Memories Configuration[/bold]")
    console.print()
    new_url = click.prompt(
        "Immich server URL",
        default=cfg.immich.url or "https://photos.example.com",
    )
    new_api_key = _prompt_for_api_key(cfg.immich.api_key)
    if not _save(ctx, {"immich.url": new_url, "immich.api_key": new_api_key}):
        ctx.exit(1)

    if click.confirm("Test connection now?", default=True):
        from immich_memories.api.immich import ImmichAPIError, SyncImmichClient

        try:
            with SyncImmichClient(
                base_url=new_url,
                api_key=new_api_key,
                api_version=cfg.immich.api_version,
            ) as client:
                user = client.get_current_user()
                print_success(f"Connected! Logged in as: {user.name or user.email}")
        except ImmichAPIError as e:
            print_error(f"Connection failed: {e}")


def register_config_commands(main: click.Group) -> None:
    """Register config, people, years, and preflight commands on the main CLI group."""

    @main.group(invoke_without_command=True)
    @click.option("--url", "-u", type=str, help="Immich server URL")
    @click.option("--api-key", "-k", type=str, help="Immich API key")
    @click.option("--show", "-s", is_flag=True, help="Same as `config show`")
    @click.pass_context
    def config(ctx: click.Context, url: str | None, api_key: str | None, show: bool) -> None:
        """Configure the Immich connection, or inspect where each setting comes from.

        Without a subcommand this sets the Immich URL and API key, prompting for
        them when no option is given. Settings saved here go to the database, below
        environment variables and config.yaml, which this never writes. The API key
        is a secret: saving it needs IMMICH_MEMORIES_SECRET_KEY.
        """
        if ctx.invoked_subcommand:
            return
        if show:
            _show(ctx, ())
            return
        _configure(ctx, url, api_key)

    @config.command("test")
    @click.pass_context
    def config_test(ctx: click.Context) -> None:
        """Check the Immich connection and the API version it resolves (read-only)."""
        from immich_memories.preflight import CheckStatus, check_immich

        result = check_immich(ctx.obj["config"])
        details = f": {result.details}" if result.details else ""
        if result.status is CheckStatus.OK:
            print_success(f"{result.message}{details}")
            return
        print_error(f"{result.message}{details}")
        ctx.exit(1)

    @config.command("show")
    @click.argument("prefixes", nargs=-1)
    @click.pass_context
    def config_show(ctx: click.Context, prefixes: tuple[str, ...]) -> None:
        """Every setting with its value and source: env, file, database or default.

        Secrets are masked. An env or file source names the variable or the
        config.yaml key that sets it. Give key prefixes (`llm`, `immich.url`) to
        show only those.
        """
        _show(ctx, prefixes)

    @config.command("move-to-db")
    @click.argument("keys", nargs=-1, required=True)
    @click.pass_context
    def config_move_to_db(ctx: click.Context, keys: tuple[str, ...]) -> None:
        """Move settings out of config.yaml into the database.

        KEYS are runtime paths such as `llm.model` (no `advanced.` prefix). Each
        value is saved to the database, then its line is removed from config.yaml,
        so the UI can edit it. The rest of the file keeps its values and `${VAR}`
        references but loses its comments; the old file is kept as config.yaml.bak.
        Nothing moves without this command.
        """
        from immich_memories.settings_edit import SettingRefused, move_to_database

        try:
            backup = move_to_database(list(keys), path=_config_file(ctx))
        except SettingRefused as refusal:
            print_error(str(refusal))
            ctx.exit(1)
        print_success(f"Moved to the database: {', '.join(keys)} (previous file: {backup})")

    @main.command()
    @click.pass_context
    def years(ctx: click.Context) -> None:
        """List years with video content."""
        cfg = ctx.obj["config"]

        if not cfg.immich.url or not cfg.immich.api_key:
            print_error("Immich not configured. Run 'immich-memories config' first.")
            sys.exit(1)

        from immich_memories.api.immich import SyncImmichClient

        with SyncImmichClient(
            base_url=cfg.immich.url,
            api_key=cfg.immich.api_key,
            api_version=cfg.immich.api_version,
        ) as client:
            years_list = client.get_available_years()

            console.print("[bold]Years with video content:[/bold]")
            for year in years_list:
                console.print(f"  \u2022 {year}")

    @main.command()
    @click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
    @click.pass_context
    def preflight(ctx: click.Context, verbose: bool) -> None:
        """Run preflight checks to validate all provider connections.

        Checks:
        - Immich server connection and API key
        - LLM availability (Ollama or OpenAI-compatible)
        - Title rendering (GPU or PIL fallback)
        - Pinned DINOv2 encoder export (presence and digest)
        - Caption endpoint (advertises the accepted alias)
        - Configured paths that are not on this host
        - Notification delivery health
        - Hardware acceleration
        """
        from immich_memories.preflight import CheckStatus, run_preflight_checks

        config = ctx.obj["config"]

        console.print("[bold]Running Preflight Checks[/bold]")
        console.print()

        checks = run_preflight_checks(config)

        # Build results table
        table = Table(title="Provider Status")
        table.add_column("Provider", style="cyan")
        table.add_column("Status")
        table.add_column("Message")
        if verbose:
            table.add_column("Details", style="dim")

        status_styles = {
            CheckStatus.OK: "[green]OK[/green]",
            CheckStatus.WARNING: "[yellow]WARNING[/yellow]",
            CheckStatus.ERROR: "[red]ERROR[/red]",
            CheckStatus.SKIPPED: "[dim]SKIPPED[/dim]",
        }

        for check in checks:
            row = [
                check.name,
                status_styles.get(check.status, str(check.status)),
                check.message,
            ]
            if verbose:
                row.append(check.details or "")
            table.add_row(*row)

        console.print(table)
        console.print()

        # Summary
        ok_count = sum(1 for c in checks if c.status == CheckStatus.OK)
        warn_count = sum(1 for c in checks if c.status == CheckStatus.WARNING)
        error_count = sum(1 for c in checks if c.status == CheckStatus.ERROR)
        skip_count = sum(1 for c in checks if c.status == CheckStatus.SKIPPED)

        all_ok = all(c.status != CheckStatus.ERROR for c in checks)
        has_warnings = any(c.status == CheckStatus.WARNING for c in checks)

        if all_ok:
            if has_warnings:
                print_info(
                    f"Preflight complete: {ok_count} OK, {warn_count} warnings, {skip_count} skipped"
                )
            else:
                print_success(f"All checks passed! ({ok_count} OK, {skip_count} skipped)")
        else:
            print_error(f"Preflight failed: {error_count} errors, {warn_count} warnings")
            console.print()
            console.print("[dim]Fix the errors above before proceeding.[/dim]")
            sys.exit(1)
