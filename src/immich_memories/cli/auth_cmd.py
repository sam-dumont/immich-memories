"""Sign-in: a new generated password when the one from the first start is lost."""

from __future__ import annotations

import sys

import click

from immich_memories.cli._helpers import console, print_error


def register_auth_commands(cli_group: click.Group) -> None:
    """Register the `auth` group on the main CLI group."""

    @cli_group.group()
    def auth() -> None:
        """The web UI's sign-in."""

    @auth.command("reset-password")
    @click.pass_context
    def reset_password(ctx: click.Context) -> None:
        """Make a new sign-in password, print it once, and sign every browser out.

        For the password the server generated because none is configured. Only its hash is
        kept. A password you set in auth.password is changed there instead.
        """
        from immich_memories.config.loader import config_state_dir
        from immich_memories.web.generated_login import login_path, reset_generated_login
        from immich_memories.web.session_validity import end_sessions

        config = ctx.obj["config"]
        if not config.auth.generates_login:
            print_error(
                "Sign-in does not use a generated password here: it is off, uses OIDC or header "
                "sign-in, or auth.password is set. Change auth.password to change that one."
            )
            sys.exit(1)
        password = reset_generated_login(login_path(config_state_dir()))
        end_sessions(config, None)
        console.print(f"username: {config.auth.sign_in_username}", markup=False, highlight=False)
        console.print(f"password: {password}", markup=False, highlight=False)
        console.print(
            "Shown once; only its hash is kept. Every browser signed in before is signed out.",
            markup=False,
            highlight=False,
        )
