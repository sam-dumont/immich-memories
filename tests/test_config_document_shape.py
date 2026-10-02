"""Configuration documents must not silently become defaults."""

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import Config


@pytest.mark.parametrize("text", ["1", "true", "false", "0", "[]", "[1]", "private-value"])
def test_non_mapping_yaml_has_a_clean_error_without_echoing_its_value(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(yaml.YAMLError, match="mapping"):
        Config.from_yaml(path, stored={})
    result = CliRunner().invoke(main, ["-c", str(path), "config", "--help"])
    assert result.exit_code != 0
    assert "mapping" in result.output
    assert "private-value" not in result.output


def test_misspelled_auth_setting_is_not_silently_ignored(tmp_path):
    from pydantic import ValidationError

    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  auth:\n    enabld: true\n")
    with pytest.raises(ValidationError, match="enabld"):
        Config.from_yaml(path, stored={})
