"""Ignored configuration typos remain visible without exposing their values."""

from immich_memories.config import Config


def test_nested_file_typo_warns_once_without_value(tmp_path, caplog):
    path = tmp_path / "config.yaml"
    path.write_text("trips:\n  homebase_lattitude: secret-sentinel\n")
    config = Config.from_yaml(path, stored={})
    assert config.unknown_keys == ("file: trips.homebase_lattitude",)
    messages = [record.message for record in caplog.records]
    assert sum("trips.homebase_lattitude" in message for message in messages) == 1
    assert "secret-sentinel" not in "\n".join(messages)


def test_env_typo_and_aliases_are_key_only(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("IMMICH_MEMORIES_TRIPS__HOMEBASE_LATTITUDE", "secret-env-sentinel")
    for name in (
        "IMMICH_MEMORIES_AUTH_USERNAME",
        "IMMICH_MEMORIES_SECRET_KEY",
        "IMMICH_MEMORIES_DEPLOYMENT_READER_URL",
        "IMMICH_MEMORIES_DATABASE_URL",
    ):
        monkeypatch.setenv(name, "")
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.unknown_keys == ("env: IMMICH_MEMORIES_TRIPS__HOMEBASE_LATTITUDE",)
    assert "secret-env-sentinel" not in caplog.text


def test_json_section_environment_reports_nested_typo(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("IMMICH_MEMORIES_TRIPS", '{"homebase_lattitude":"json-secret"}')
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.unknown_keys == ("env: IMMICH_MEMORIES_TRIPS__HOMEBASE_LATTITUDE",)
    assert "json-secret" not in caplog.text


def test_preflight_reports_only_ignored_key_names(tmp_path):
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_config_keys import check_unknown_config_keys

    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  llm:\n    api_keey: report-secret\n")
    checks = check_unknown_config_keys(Config.from_yaml(path, stored={}))
    assert len(checks) == 1
    assert checks[0].status == CheckStatus.WARNING
    assert checks[0].message == "Ignored unknown key: file: llm.api_keey"


def test_config_show_lists_ignored_names(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from immich_memories.cli import main

    monkeypatch.setenv("IMMICH_MEMORIES_SKIP_STORED_SETTINGS", "1")
    path = tmp_path / "config.yaml"
    path.write_text("trips:\n  homebase_lattitude: output-secret\n")
    result = CliRunner().invoke(main, ["--config", str(path), "config", "show"])
    assert result.exit_code == 0, result.output
    assert "Ignored unknown key: file: trips.homebase_lattitude" in result.output
    assert "output-secret" not in result.output


def test_named_accounts_and_freeform_reader_options_are_not_unknown(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "immich:\n  accounts:\n    partner:\n      url: http://partner.example:2283\n      api_key: synthetic\nadvanced:\n  llm:\n    extra_params:\n      vendor_option: true\n"
    )
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__EXTRA_PARAMS__OTHER_VENDOR_OPTION", "true")
    monkeypatch.setenv("IMMICH_MEMORIES_IMMICH__ACCOUNTS__PARTNER__API_KEY", "synthetic")
    assert Config.from_yaml(path, stored={}).unknown_keys == ()


def test_json_named_account_map_and_fp32_control(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32", "1")
    monkeypatch.setenv(
        "IMMICH_MEMORIES_IMMICH__ACCOUNTS",
        '{"partner":{"url":"http://partner.example:2283","api_key":"synthetic"}}',
    )
    assert Config.from_yaml(tmp_path / "missing.yaml", stored={}).unknown_keys == ()


def test_json_named_account_map_reports_nested_typo(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(
        "IMMICH_MEMORIES_IMMICH__ACCOUNTS",
        '{"partner":{"url":"http://partner.example:2283","api_key":"synthetic","api_keey":"secret-map-value"}}',
    )
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.unknown_keys == ("env: IMMICH_MEMORIES_IMMICH__ACCOUNTS__PARTNER__API_KEEY",)
    assert "secret-map-value" not in caplog.text


def test_json_env_field_names_follow_env_case_insensitivity(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IMMICH_MEMORIES_TRIPS", '{"HOMEBASE_LATITUDE":50.8,"HOMEBASE_LONGITUDE":4.3}'
    )
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.trips.homebase_latitude == 50.8
    assert config.unknown_keys == ()


def test_supported_service_process_controls_are_recognized(tmp_path, monkeypatch):
    for suffix in (
        "INFERENCE_ALLOW_MODEL_DOWNLOADS",
        "INFERENCE_IDLE_UNLOAD_SECONDS",
        "INFERENCE_BUNDLE",
        "INFERENCE_REQUEST_THREADS",
        "INFERENCE_PRELOAD",
        "INFERENCE_MAX_QUEUED_REQUESTS",
        "INFERENCE_MAX_IMAGE_BYTES",
        "RENDER_WORKER_MAX_JOBS",
        "RENDER_WORKER_RETENTION_SECONDS",
        "RENDER_WORKER_JOB_TIMEOUT_SECONDS",
    ):
        monkeypatch.setenv(f"IMMICH_MEMORIES_{suffix}", "1")
    assert Config.from_yaml(tmp_path / "missing.yaml", stored={}).unknown_keys == ()
