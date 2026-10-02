"""Generated configuration and parser inputs stay bounded and fail visibly."""

import pytest
import yaml
from click.testing import CliRunner
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from pydantic_settings import SettingsError

from immich_memories.api.person_expression import PersonExpression
from immich_memories.cli import main
from immich_memories.config_loader import Config
from immich_memories.free_text.reading import read_request
from tests.free_text.banked import BankedAsker


@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.text(max_size=1000))
def test_random_yaml_has_a_clean_cli_result(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    try:
        Config.from_yaml(path, stored={})
    except (yaml.YAMLError, ValidationError, SettingsError):
        result = CliRunner().invoke(main, ["-c", str(path), "config", "--help"])
        assert result.exit_code != 0
        assert "Traceback" not in result.output


@settings(
    max_examples=60,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.text(alphabet=st.characters(codec="utf-8", blacklist_characters="\x00"), max_size=100))
def test_invalid_boolean_env_does_not_silently_use_the_default(tmp_path, monkeypatch, value):
    with monkeypatch.context() as env:
        env.setenv("IMMICH_MEMORIES_SERVER__ALLOW_UNAUTHENTICATED_LAN", value)
        valid = {"0", "1", "true", "false", "t", "f", "yes", "no", "y", "n", "on", "off"}
        if value.lower() in valid:
            config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
            assert config.server.allow_unauthenticated_lan == (
                value.lower() in {"1", "true", "t", "yes", "y", "on"}
            )
        else:
            with pytest.raises((ValidationError, SettingsError)):
                Config.from_yaml(tmp_path / "missing.yaml", stored={})


@settings(max_examples=150, deadline=1000, derandomize=True)
@example("(" * 10000)
@example('"' + "x" * 17000 + '"')
@given(st.text(max_size=5000))
def test_people_expression_either_round_trips_or_refuses(text):
    try:
        expression = PersonExpression.parse(text)
    except ValueError:
        return
    assert PersonExpression.parse(expression.display_label) == expression


@settings(max_examples=100, deadline=1000, derandomize=True)
@example("word " * 1000)
@given(st.text(max_size=5000))
def test_sentence_reading_is_bounded_without_a_live_model(text):
    # WHY: the model service boundary returns a valid empty classification; parsing is real.
    answer = {"who": [], "when": [], "where": [], "what": []}
    asker = BankedAsker(answer, answer, answer)
    reading = read_request(text, asker)
    assert reading.request == text
    assert len(asker.questions) <= 3
