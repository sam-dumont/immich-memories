"""Tests for structured logging configuration."""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest

from immich_memories import logging_config
from immich_memories.logging_config import (
    JsonFormatter,
    SecretRedactionFilter,
    configure_logging,
    install_secret_redaction,
)


def _record(msg: object, args: object = (), exc_info: object = None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,  # type: ignore[arg-type]
    )


class TestConfigureLogging:
    """Test configure_logging() setup."""

    def test_text_format_default(self):
        """Default format is text with StreamHandler."""
        configure_logging(fmt="text")
        root = logging.getLogger()
        assert root.handlers
        handler = root.handlers[-1]
        assert not isinstance(handler.formatter, JsonFormatter)

    def test_json_format(self):
        """JSON format uses JsonFormatter."""
        configure_logging(fmt="json")
        root = logging.getLogger()
        handler = root.handlers[-1]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_default_is_text(self, monkeypatch):
        """Calling with no args defaults to text."""
        monkeypatch.delenv("IMMICH_MEMORIES_LOG_FORMAT", raising=False)
        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[-1]
        assert not isinstance(handler.formatter, JsonFormatter)

    def test_env_var_override(self, monkeypatch):
        """IMMICH_MEMORIES_LOG_FORMAT env var overrides default."""
        monkeypatch.setenv("IMMICH_MEMORIES_LOG_FORMAT", "json")
        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[-1]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_log_level_setting(self):
        """Log level is set correctly."""
        configure_logging(fmt="text", level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

        # Reset
        configure_logging(fmt="text", level="INFO")


class TestServerLogNoise:
    """A nightly run's log is mostly probes and start-up lines unless someone asks for them (#2244)."""

    @staticmethod
    def _access(path: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access", logging.INFO, "x.py", 1,
            '%s - "%s %s HTTP/%s" %d', ("10.0.0.1:1", "GET", path, "1.1", 200), None,
        )  # fmt: skip

    def test_health_probe_access_lines_are_dropped_and_other_requests_kept(self):
        stream = io.StringIO()
        configure_logging(fmt="text", level="INFO", stream=stream)
        access = logging.getLogger("uvicorn.access")

        for path in ("/health/live", "/health/ready", "/api/v1/runs"):
            access.handle(self._access(path))

        text = stream.getvalue()
        assert "/health" not in text
        assert "/api/v1/runs" in text

    def test_verbose_shows_the_probes_again(self):
        stream = io.StringIO()
        configure_logging(fmt="text", level="DEBUG", stream=stream)

        logging.getLogger("uvicorn.access").handle(self._access("/health/live"))

        assert "/health/live" in stream.getvalue()
        configure_logging(fmt="text", level="INFO")

    def test_alembic_is_quiet_unless_verbose(self):
        configure_logging(fmt="text", level="INFO")
        assert logging.getLogger("alembic").level == logging.WARNING

        configure_logging(fmt="text", level="DEBUG")
        assert logging.getLogger("alembic").level == logging.NOTSET
        configure_logging(fmt="text", level="INFO")


class TestJsonFormatter:
    """Test JsonFormatter output."""

    def test_format_produces_valid_json(self):
        """Format output is valid JSON with expected fields."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Hello world"
        assert "timestamp" in data

    def test_format_includes_exception(self):
        """Exception info is included in JSON output."""
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="Something failed",
                args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert any("ValueError" in line for line in data["exception"])

    def test_format_no_exception_when_none(self):
        """No exception field when exc_info is None."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="ok",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" not in data

    def test_single_line_output(self):
        """JSON output is a single line (no embedded newlines in JSON)."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="line one",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "\n" not in output


class TestSecretRedaction:
    """Known secret values never reach a formatted log line.

    Pre-config behaviour is deliberately not asserted here: redaction is armed
    by `install_secret_redaction` at config load, so anything logged before the
    config exists (startup, a config-file parse error) is unredacted by
    construction. There is no earlier moment at which the values are known.
    """

    @pytest.fixture(autouse=True)
    def _isolate_registered_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Registration accumulates process-wide, so each test starts from empty.
        monkeypatch.setattr(logging_config, "_secret_values", ())

    def test_trigger_token_in_a_message_is_redacted(self) -> None:
        install_secret_redaction(["trigger-token-from-config"])
        record = _record("POST /api/trigger rejected token=trigger-token-from-config")

        SecretRedactionFilter().filter(record)

        assert "trigger-token-from-config" not in record.getMessage()
        assert "[redacted]" in record.getMessage()

    def test_api_key_in_an_exception_is_redacted(self) -> None:
        install_secret_redaction(["immich-api-key-0123456789"])
        try:
            raise RuntimeError("upstream rejected immich-api-key-0123456789")
        except RuntimeError:
            record = _record("asset fetch failed", exc_info=sys.exc_info())

        SecretRedactionFilter().filter(record)
        rendered = logging.Formatter("%(message)s").format(record)

        assert "immich-api-key-0123456789" not in rendered
        assert "[redacted]" in rendered

    def test_api_key_in_an_exception_is_redacted_in_json_output(self) -> None:
        install_secret_redaction(["immich-api-key-0123456789"])
        try:
            raise RuntimeError("upstream rejected immich-api-key-0123456789")
        except RuntimeError:
            record = _record("asset fetch failed", exc_info=sys.exc_info())

        SecretRedactionFilter().filter(record)
        rendered = JsonFormatter().format(record)

        assert "immich-api-key-0123456789" not in rendered
        assert any("RuntimeError" in line for line in json.loads(rendered)["exception"])

    def test_a_record_carrying_no_secret_is_unchanged(self) -> None:
        install_secret_redaction(["immich-api-key-0123456789"])
        record = _record("selected %d clips from %s", args=(42, "Summer 2024"))
        formatter = logging.Formatter("%(message)s")
        before = formatter.format(record)

        SecretRedactionFilter().filter(record)

        assert formatter.format(record) == before == "selected 42 clips from Summer 2024"

    def test_secrets_below_the_length_floor_are_never_applied(self) -> None:
        # 0, 3 and 7 characters -- all under MIN_REDACTABLE_SECRET_LENGTH.
        install_secret_redaction(["", "abc", "short12"])
        record = _record("abc short12 appear in an album title")

        SecretRedactionFilter().filter(record)

        assert record.getMessage() == "abc short12 appear in an album title"

    def test_handlers_configured_by_configure_logging_redact(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        install_secret_redaction(["trigger-token-from-config"])
        configure_logging(fmt="text", level="INFO")

        logging.getLogger("test.redaction").warning("token=trigger-token-from-config")

        printed = capsys.readouterr().err
        assert "trigger-token-from-config" not in printed
        assert "[redacted]" in printed

    def test_loading_a_config_arms_redaction_for_its_trigger_token(self) -> None:
        from immich_memories.config import Config, set_config

        set_config(Config(server={"trigger_token": "workflow-token-secret-value"}))
        record = _record("rejected token=workflow-token-secret-value")

        SecretRedactionFilter().filter(record)

        assert "workflow-token-secret-value" not in record.getMessage()
