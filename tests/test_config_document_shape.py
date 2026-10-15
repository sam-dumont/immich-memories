"""Configuration documents must not silently become defaults."""

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config.loader import Config


@pytest.mark.parametrize("text", ["1", "true", "false", "0", "[]", "[1]", "private-value"])
def test_non_mapping_yaml_has_a_clean_error_without_echoing_its_value(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(yaml.YAMLError, match="mapping"):
        Config.from_yaml(path, stored={})
    result = CliRunner().invoke(main, ["-c", str(path), "config", "show"])
    assert result.exit_code != 0
    # WHY: the fallback used to echo str(error), which can quote the source context --
    # exactly where a secret in config.yaml sits. The message names the fix, never the text.
    # Valid YAML of the wrong shape is not a syntax error (#2380): the message says what
    # the file must hold.
    assert "must be a mapping of setting names to values" in result.output
    assert "YAML syntax error" not in result.output
    assert "private-value" not in result.output


def test_misspelled_auth_setting_is_not_silently_ignored(tmp_path):
    from pydantic import ValidationError

    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  auth:\n    enabld: true\n")
    with pytest.raises(ValidationError, match="enabld"):
        Config.from_yaml(path, stored={})
