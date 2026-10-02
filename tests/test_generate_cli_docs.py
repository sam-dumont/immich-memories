"""The published reference covers nested Click commands and readable examples."""

import click
from scripts.generate_cli_docs import _format_help, generate_reference


def test_reference_includes_nested_groups_and_skips_hidden_commands() -> None:
    root = click.Group()
    store = click.Group(name="store")
    facts = click.Group(name="facts")
    facts.add_command(click.Command(name="inspect", help="Inspect one fact."))
    facts.add_command(click.Command(name="internal", hidden=True))
    store.add_command(facts)
    root.add_command(store)

    reference = generate_reference(root)

    assert "#### `store facts inspect`" in reference
    assert "immich-memories store facts inspect [OPTIONS]" in reference
    assert "internal" not in reference


def test_click_examples_are_highlighted_without_control_characters() -> None:
    rendered = _format_help(
        "Prepare facts.\n\n\b\nExamples:\n  immich-memories prepare --year 2026\n  \b"
    )

    assert "```bash" in rendered
    assert "immich-memories prepare --year 2026" in rendered
    assert "# Examples:" in rendered
    assert "\b" not in rendered


def test_preformatted_output_stays_plain_text() -> None:
    rendered = _format_help("\b\nstatus  ready\nrows    42")

    assert "```text" in rendered
    assert "status  ready" in rendered


def test_reference_uses_descriptive_dynamic_defaults() -> None:
    def reference(year: int) -> str:
        root = click.Group()
        root.add_command(
            click.Command(
                "scan",
                params=[click.Option(["--until"], default=year, show_default="current year")],
            )
        )
        return generate_reference(root)

    assert reference(2026) == reference(2027)
    assert "current year" in reference(2026)


def test_reference_includes_global_options_and_real_argument_usage() -> None:
    root = click.Group(params=[click.Option(["--config"], type=click.Path(), help="Config path")])
    root.add_command(
        click.Command(
            "inspect",
            params=[
                click.Argument(["run_id"]),
                click.Argument(["assets"], nargs=-1),
                click.Option(["--tag"], multiple=True, required=True),
            ],
        )
    )
    reference = generate_reference(root)

    assert "## Global options" in reference
    assert "`--config`" in reference
    assert "immich-memories inspect [OPTIONS] RUN_ID [ASSETS]..." in reference
    assert "required" in reference
    assert "repeatable" in reference


def test_saved_cut_render_rejects_unknown_output_choices_before_loading_a_run() -> None:
    from click.testing import CliRunner

    from immich_memories.cli.runs_render import register_render_command

    runs = click.Group()
    register_render_command(runs)
    for option in ("--resolution", "--orientation", "--scale-mode"):
        result = CliRunner().invoke(runs, ["render", option, "unknown"])
        assert result.exit_code == 2
        assert "Invalid value" in result.output
