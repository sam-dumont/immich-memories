"""The printed preflight table's Output directory row names the path, its source and the mount (#2218)."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.preflight_output import ENV_VARIABLE, output_directory_rows


def _printed_output_row(
    tmp_path, monkeypatch, *, env_dir=None, file_dir=None, in_container=False, own_mount=False
):
    monkeypatch.delenv(ENV_VARIABLE, raising=False)
    if env_dir:
        monkeypatch.setenv(ENV_VARIABLE, str(env_dir))
    config_path = tmp_path / "c.yaml"
    config_path.write_text(
        "immich:\n  url: http://immich\n  api_key: k\n"
        + (f"output:\n  directory: {file_dir}\n" if file_dir else "")
    )

    def only_the_output_rows(config):
        return output_directory_rows(config)

    with (
        patch("immich_memories.cli.init_config_dir"),
        # WHY: the other checks reach Immich, an LLM and the GPU; only the output rows are the subject.
        patch("immich_memories.preflight.run_preflight_checks", only_the_output_rows),
        patch("immich_memories.preflight_output.running_in_container", return_value=in_container),
        # WHY: a real mount point cannot be created in a unit test; the device ids stand in for one.
        patch(
            "immich_memories.preflight_output._device",
            side_effect=lambda path: 1 if str(path) == "/" else (2 if own_mount else 1),
        ),
        # WHY: the config path is a host file; the origin reads it to see what the env var shadows.
        patch("immich_memories.config_loader.get_config_path", return_value=config_path),
    ):
        result = CliRunner().invoke(
            main, ["-c", str(config_path), "preflight"], env={"COLUMNS": "300"}
        )
    # Rich folds a long temp path across lines; compare the table with its borders and blanks gone.
    flat = "".join(ch for ch in result.output if ch not in "│ \n")
    return flat.split("Outputdirectory")[1:]


def test_the_table_row_shows_the_path_and_the_env_var_that_set_it(tmp_path, monkeypatch):
    films = tmp_path / "films"

    rows = _printed_output_row(tmp_path, monkeypatch, env_dir=films)

    assert len(rows) == 1
    assert str(films) in rows[0]
    assert ENV_VARIABLE in rows[0]
    assert "writable" in rows[0]


def test_the_table_row_says_config_yaml_when_the_file_set_it(tmp_path, monkeypatch):
    films = tmp_path / "from-file"

    rows = _printed_output_row(tmp_path, monkeypatch, file_dir=films)

    assert str(films) in rows[0]
    assert "config.yaml" in rows[0]


def test_the_table_row_says_built_in_default_when_nothing_set_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    rows = _printed_output_row(tmp_path, monkeypatch)

    assert "built-indefault" in rows[0]


def test_an_env_var_that_shadows_config_yaml_prints_both_rows(tmp_path, monkeypatch):
    rows = _printed_output_row(
        tmp_path, monkeypatch, env_dir=tmp_path / "env", file_dir=tmp_path / "file"
    )

    assert len(rows) == 2
    assert any("overridesconfig.yaml" in row for row in rows)


def test_the_table_row_says_mounted_volume_in_a_container(tmp_path, monkeypatch):
    rows = _printed_output_row(
        tmp_path, monkeypatch, env_dir=tmp_path / "out", in_container=True, own_mount=True
    )

    assert "mountedvolume" in rows[0]
    assert len(rows) == 1


def test_the_table_row_warns_when_a_container_output_is_not_a_mount(tmp_path, monkeypatch):
    rows = _printed_output_row(tmp_path, monkeypatch, env_dir=tmp_path / "out", in_container=True)

    assert len(rows) == 2
    assert any("notamountedvolume" in row for row in rows)
