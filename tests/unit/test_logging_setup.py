"""Tests for region_template.logging_setup — spec §H.1."""
from __future__ import annotations

import json
import logging
import os
import re

import pytest
import structlog
import structlog.contextvars

import region_template.logging_setup as _ls_mod
from region_template.logging_setup import _remap_warning_to_warn, configure_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$"
)


def _parse_line(captured: str) -> dict:
    """Return the first non-empty JSON line from captured stdout."""
    for raw in captured.splitlines():
        stripped = raw.strip()
        if stripped:
            return json.loads(stripped)
    raise AssertionError(f"No JSON output found in: {captured!r}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """
    Reset structlog + stdlib logging between tests so configure_logging
    always starts from a clean state.
    """
    _ls_mod._configured = False
    structlog.contextvars.clear_contextvars()
    # Remove all handlers from root logger to avoid bleed.
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    yield
    # Cleanup after test
    structlog.contextvars.clear_contextvars()
    _ls_mod._configured = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportAndSmoke:
    def test_configure_logging_runs_without_error(self):
        """Uppercase level is accepted; call does not raise."""
        configure_logging(region_name="amygdala", level="INFO")


class TestJSONOutputShape:
    def test_required_keys_present(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("handler_complete", msg="Handler done")

        out = capsys.readouterr().out
        data = _parse_line(out)

        for key in ("ts", "level", "region", "event", "msg"):
            assert key in data, f"Missing key {key!r} in {data}"

    def test_key_values_correct(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("handler_complete", msg="Handler done")

        data = _parse_line(capsys.readouterr().out)

        assert data["region"] == "amygdala"
        assert data["level"] == "info"
        assert data["event"] == "handler_complete"
        assert data["msg"] == "Handler done"

    def test_ts_matches_iso_utc_pattern(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("ts_check")

        data = _parse_line(capsys.readouterr().out)

        assert "ts" in data, "Missing 'ts' key"
        assert _TS_RE.match(data["ts"]), (
            f"ts value {data['ts']!r} does not match ISO-8601-UTC pattern"
        )

    def test_no_timestamp_key(self, capsys):
        """Ensure legacy 'timestamp' key is NOT emitted (spec uses 'ts')."""
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("shape_check")

        data = _parse_line(capsys.readouterr().out)
        assert "timestamp" not in data, "Key 'timestamp' must not appear; spec uses 'ts'"


class TestCorrelationIdPropagation:
    def test_correlation_id_bound_propagates(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        structlog.contextvars.bind_contextvars(correlation_id="abc123")
        log = structlog.get_logger()
        log.info("corr_check")

        data = _parse_line(capsys.readouterr().out)
        assert data.get("correlation_id") == "abc123"

    def test_correlation_id_absent_after_clear(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        structlog.contextvars.bind_contextvars(correlation_id="abc123")
        structlog.contextvars.clear_contextvars()

        # Re-bind region/pid that configure_logging set (cleared above)
        structlog.contextvars.bind_contextvars(
            region="amygdala", pid=os.getpid()
        )

        log = structlog.get_logger()
        log.info("corr_absent_check")

        data = _parse_line(capsys.readouterr().out)
        assert "correlation_id" not in data, (
            f"correlation_id should not appear after clear_contextvars; got {data}"
        )


class TestPidAlwaysBound:
    def test_pid_present_and_correct(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("pid_check")

        data = _parse_line(capsys.readouterr().out)
        assert "pid" in data, "Missing 'pid' key"
        assert data["pid"] == os.getpid()


class TestIdempotency:
    def test_double_call_does_not_crash(self):
        configure_logging(region_name="amygdala", level="info")
        configure_logging(region_name="amygdala", level="info")  # second call

    def test_double_call_emits_exactly_one_line(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("idempotency_check")

        out = capsys.readouterr().out
        json_lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(json_lines) == 1, (
            f"Expected exactly 1 JSON line, got {len(json_lines)}: {json_lines}"
        )


class TestLevelFiltering:
    def test_info_suppressed_at_error_level(self, capsys):
        configure_logging(region_name="amygdala", level="error")
        log = structlog.get_logger()
        log.info("should_be_filtered")

        out = capsys.readouterr().out
        assert out.strip() == "", (
            f"Expected no output at ERROR level for info(); got: {out!r}"
        )

    def test_error_passes_at_error_level(self, capsys):
        configure_logging(region_name="amygdala", level="error")
        log = structlog.get_logger()
        log.error("should_pass")

        out = capsys.readouterr().out
        assert out.strip() != "", "Expected output for error() at ERROR level"


class TestLevelNames:
    def test_info_emits_lowercase_level(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.info("level_case_check")

        data = _parse_line(capsys.readouterr().out)
        assert data["level"] == "info"

    def test_warn_emits_warn_not_warning(self, capsys):
        """
        Spec §H.1.2 requires level='warn', not 'warning'.

        structlog's add_log_level maps the 'warn' method -> 'warning'
        (since 'warn' is deprecated stdlib). A custom _remap_warning_to_warn
        processor converts 'warning' -> 'warn' to comply with the spec.
        """
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.warn("warn_level_check")

        data = _parse_line(capsys.readouterr().out)
        assert data["level"] == "warn", (
            f"Spec §H.1.2 requires 'warn'; got {data['level']!r}. "
            "A remap processor must convert 'warning' -> 'warn'."
        )

    def test_error_emits_lowercase_error(self, capsys):
        configure_logging(region_name="amygdala", level="info")
        log = structlog.get_logger()
        log.error("error_level_check")

        data = _parse_line(capsys.readouterr().out)
        assert data["level"] == "error"

    def test_debug_emits_lowercase_debug(self, capsys):
        configure_logging(region_name="amygdala", level="debug")
        log = structlog.get_logger()
        log.debug("debug_level_check")

        data = _parse_line(capsys.readouterr().out)
        assert data["level"] == "debug"


# ---------------------------------------------------------------------------
# New tests (review findings)
# ---------------------------------------------------------------------------

# Alias for clarity in new tests — same fixture as the autouse one above.
reset_logging = _reset_logging_state


def test_stdlib_third_party_output_is_json(capsys, reset_logging):
    """Third-party stdlib logging is rendered as JSON via ProcessorFormatter.

    Expected shape for stdlib-originated records:
      {"level": ..., "ts": ..., "event": ...}
    The exact key for the message depends on how ProcessorFormatter maps
    the stdlib LogRecord: structlog uses "event" for the message body.
    """
    configure_logging(region_name="test", level="debug")
    logging.getLogger("test.thirdparty").info("hello from stdlib")
    captured = capsys.readouterr().out.strip()
    # There should be at least one non-empty line.
    lines = [ln for ln in captured.splitlines() if ln.strip()]
    assert lines, f"Expected JSON output from stdlib logger, got: {captured!r}"
    parsed = json.loads(lines[-1])
    # Must have level and ts (from shared_processors chain).
    assert "level" in parsed, f"Missing 'level' key in stdlib JSON: {parsed}"
    assert "ts" in parsed, f"Missing 'ts' key in stdlib JSON: {parsed}"
    # Message appears as 'event' (structlog convention) or 'msg' fallback.
    assert "event" in parsed or "msg" in parsed, (
        f"Expected 'event' or 'msg' key in stdlib JSON: {parsed}"
    )


def test_remap_warning_to_warn_processor_direct():
    """Processor transforms level='warning' to 'warn' and leaves others alone."""
    # level == "warning" gets remapped
    assert _remap_warning_to_warn(None, "warning", {"level": "warning", "other": "keep"}) == {
        "level": "warn",
        "other": "keep",
    }
    # other levels untouched
    for lv in ("info", "debug", "error"):
        result = _remap_warning_to_warn(None, lv, {"level": lv, "x": 1})
        assert result == {"level": lv, "x": 1}
    # missing "level" key does not crash
    assert _remap_warning_to_warn(None, "info", {"no_level": True}) == {"no_level": True}


def test_exception_info_rendered_in_json(capsys, reset_logging):
    """exc_info=True produces a JSON line with an exception/traceback field.

    structlog's format_exc_info processor converts exc_info=True into an
    'exception' key containing the formatted traceback string.
    """
    configure_logging(region_name="test", level="debug")
    try:
        raise ValueError("test error")
    except ValueError:
        structlog.get_logger().error("caught_error", exc_info=True)
    captured = capsys.readouterr().out.strip()
    parsed = json.loads(captured.splitlines()[-1])
    # Either 'exception' or 'exc_info' should be present and non-empty.
    assert "exception" in parsed or "exc_info" in parsed, (
        f"Expected 'exception' or 'exc_info' key in JSON; got keys: {list(parsed.keys())}"
    )
    assert "ValueError" in json.dumps(parsed), (
        f"Expected 'ValueError' in exception output; got: {parsed}"
    )
    assert "test error" in json.dumps(parsed), (
        f"Expected 'test error' in exception output; got: {parsed}"
    )
