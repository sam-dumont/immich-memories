"""Preflight says where the output directory came from and warns when films would be lost (#2200)."""

from __future__ import annotations

from pathlib import Path

from immich_memories.preflight import CheckStatus
from immich_memories.preflight_output import (
    ENV_VARIABLE,
    OutputOrigin,
    output_directory_warnings,
    output_origin,
)


def test_an_env_var_that_shadows_a_different_config_value_is_a_warning_naming_both():
    origin = output_origin(env={ENV_VARIABLE: "/app/output"}, config_file_value="/output")

    rows = output_directory_warnings(
        Path("/app/output"), origin, in_container=False, device_of=lambda _path: 1
    )

    assert [row.status for row in rows] == [CheckStatus.WARNING]
    assert ENV_VARIABLE in rows[0].message
    assert "/app/output" in rows[0].message
    assert "/output" in rows[0].message


def test_the_origin_names_the_env_var_the_file_or_the_default():
    assert (
        "IMMICH_MEMORIES_OUTPUT__DIRECTORY"
        in output_origin(env={ENV_VARIABLE: "/app/output"}, config_file_value=None).describe()
    )
    assert "config.yaml" in output_origin(env={}, config_file_value="/output").describe()
    assert output_origin(env={}, config_file_value=None).describe() == "from the built-in default"


def test_an_env_var_that_agrees_with_the_config_is_not_a_warning():
    origin = output_origin(env={ENV_VARIABLE: "/output"}, config_file_value="/output")

    assert (
        output_directory_warnings(
            Path("/output"), origin, in_container=False, device_of=lambda _path: 1
        )
        == []
    )


def test_a_container_output_on_the_writable_layer_is_a_warning():
    origin = OutputOrigin(source="default", value=None, shadowed=None)
    devices = {Path("/app/output"): 7, Path("/"): 7}

    rows = output_directory_warnings(
        Path("/app/output"), origin, in_container=True, device_of=devices.__getitem__
    )

    assert [row.status for row in rows] == [CheckStatus.WARNING]
    assert "restart" in rows[0].message


def test_a_container_output_on_its_own_mount_is_fine(tmp_path):
    origin = OutputOrigin(source="default", value=None, shadowed=None)
    devices = {tmp_path: 9, Path("/"): 7}

    assert (
        output_directory_warnings(
            tmp_path / "films", origin, in_container=True, device_of=devices.__getitem__
        )
        == []
    )


def test_a_host_run_never_asks_about_mounts():
    origin = OutputOrigin(source="default", value=None, shadowed=None)

    assert (
        output_directory_warnings(
            Path("/films"), origin, in_container=False, device_of=lambda _path: 7
        )
        == []
    )


def test_the_writable_row_names_where_the_directory_came_from(tmp_path):
    from immich_memories.preflight_run import check_output_directory

    row = check_output_directory(
        tmp_path / "films", output_origin(env={ENV_VARIABLE: str(tmp_path)}, config_file_value=None)
    )

    assert row.status is CheckStatus.OK
    assert row.details == f"{tmp_path / 'films'} (from {ENV_VARIABLE})"
