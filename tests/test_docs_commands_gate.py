"""Static documentation checks reject invalid examples without running commands."""

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_docs_commands import check_cli, check_page  # noqa: E402


def commands() -> click.Group:
    @click.group()
    def root():
        raise AssertionError("The checker must not invoke callbacks")

    @root.group()
    def runs():
        raise AssertionError("The checker must not invoke callbacks")

    @runs.command()
    @click.argument("run_id")
    @click.option("--format", type=click.Choice(["json", "text"]))
    def show(run_id, format):
        raise AssertionError("The checker must not invoke callbacks")

    @root.command()
    @click.option("--birthday", is_flag=False, flag_value="auto")
    @click.option("--person")
    def generate(birthday, person):
        raise AssertionError("The checker must not invoke callbacks")

    return root


def test_invalid_nested_command_and_option_are_rejected():
    assert "unknown subcommand" in check_cli(["runs", "invented"], commands())[0]
    assert "unknown option" in check_cli(["runs", "show", "RUN_ID", "--invented"], commands())[0]


def test_literal_choices_and_required_arguments_are_checked():
    assert check_cli(["runs", "show", "RUN_ID", "--format", "json"], commands()) == []
    assert "not one of" in check_cli(["runs", "show", "RUN_ID", "--format", "csv"], commands())[0]
    assert "requires" in check_cli(["runs", "show"], commands())[0]


def test_optional_value_flags_do_not_consume_the_following_option():
    assert check_cli(["generate", "--birthday", "--person", "Riley"], commands()) == []
    assert check_cli(["generate", "--birthday", "07-21", "--person", "Riley"], commands()) == []


def test_shell_wrappers_do_not_turn_namespace_names_into_cli_calls(tmp_path, monkeypatch):
    import check_docs_commands

    monkeypatch.setattr(check_docs_commands, "ROOT", tmp_path)
    page = tmp_path / "guide.md"
    page.write_text(
        "```bash\nkubectl -n immich-memories get pods\ndocker compose exec immich-memories immich-memories runs show RUN_ID\nkubectl -n immich-memories exec deploy/app -- immich-memories runs show RUN_ID\n```\n"
    )
    errors, checked = check_page(page, commands(), set())
    assert errors == []
    assert checked == 2


def test_unknown_make_targets_are_rejected(tmp_path, monkeypatch):
    import check_docs_commands

    monkeypatch.setattr(check_docs_commands, "ROOT", tmp_path)
    page = tmp_path / "guide.md"
    page.write_text("```bash\nmake build imaginary\n```\n")
    errors, checked = check_page(page, commands(), {"build"})
    assert checked == 2
    assert "unknown Make target imaginary" in errors[0]


def test_generated_group_usage_accepts_command_placeholder():
    assert check_cli(["runs", "[OPTIONS]", "COMMAND", "[ARGS]..."], commands()) == []
    assert "unknown subcommand" in check_cli(["runs", "COMMAND"], commands())[0]
    assert "unknown subcommand" in check_cli(["invented", "[OPTIONS]", "COMMAND"], commands())[0]
