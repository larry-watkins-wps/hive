"""Integration tests for ``tools/hive_cli.py``.

These tests mock ``subprocess.run`` / ``subprocess.Popen`` so that no real
Docker daemon is required.  Real-docker smoke tests belong to Phase 9.

Task 6.2, per spec §G.1/G.3/G.5/G.6 and plan v0 scope.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tools.hive_cli import app

pytestmark = pytest.mark.integration

# Named exit codes — keep ruff PLR2004 quiet on "magic values".
EXIT_OK = 0
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    """Build a ``CliRunner`` with split stdout/stderr.

    Typer 0.23+ reliably supports ``mix_stderr=False`` via Click 8.
    """
    return CliRunner(mix_stderr=False)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# ``hive up``
# ---------------------------------------------------------------------------


def test_up_default_invokes_compose_up_detached():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["up"])
    assert result.exit_code == EXIT_OK, result.output
    args, kwargs = m_run.call_args
    assert args[0] == ["docker", "compose", "up", "-d"]
    assert kwargs.get("cwd") is not None
    # cwd must be the repo root (the directory containing docker-compose.yaml)
    assert (kwargs["cwd"] / "docker-compose.yaml").is_file()


def test_up_dev_only_starts_broker(monkeypatch):
    monkeypatch.delenv("HIVE_ENV", raising=False)
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["up", "--dev"])
    assert result.exit_code == EXIT_OK, result.output
    args, kwargs = m_run.call_args
    assert args[0] == ["docker", "compose", "up", "-d", "broker"]


def test_up_dev_rejected_in_prod(monkeypatch):
    monkeypatch.setenv("HIVE_ENV", "prod")
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        result = runner.invoke(app, ["up", "--dev"])
    assert result.exit_code == EXIT_USAGE
    assert m_run.call_count == 0
    assert "--dev" in result.stderr
    assert "prod" in result.stderr.lower()


def test_up_no_docker_without_mosquitto_binary(monkeypatch):
    monkeypatch.delenv("HIVE_ENV", raising=False)
    runner = _runner()
    with (
        patch("tools.hive_cli.shutil.which", return_value=None) as mock_which,
        patch("tools.hive_cli.subprocess.Popen") as m_popen,
        patch("tools.hive_cli.subprocess.run") as m_run,
    ):
        result = runner.invoke(app, ["up", "--no-docker", "--region", "foo"])
    assert result.exit_code == EXIT_USAGE
    assert m_popen.call_count == 0
    assert m_run.call_count == 0
    assert "mosquitto" in result.stderr.lower()
    # Guard against the check ever moving: mosquitto-binary probe must have run.
    assert mock_which.called
    assert mock_which.call_args.args[0] == "mosquitto"


# ---------------------------------------------------------------------------
# ``hive down``
# ---------------------------------------------------------------------------


def test_down_default_invokes_compose_down():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["down"])
    assert result.exit_code == EXIT_OK, result.output
    args, _ = m_run.call_args
    assert args[0] == ["docker", "compose", "down"]


def test_down_fast_passes_timeout_one():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["down", "--fast"])
    assert result.exit_code == EXIT_OK, result.output
    args, _ = m_run.call_args
    assert args[0] == ["docker", "compose", "down", "--timeout", "1"]


# ---------------------------------------------------------------------------
# ``hive status``
# ---------------------------------------------------------------------------


def test_status_lists_running_services():
    runner = _runner()
    ndjson = (
        json.dumps(
            {
                "Name": "mosquitto",
                "Service": "broker",
                "State": "running",
                "Health": "healthy",
            }
        )
        + "\n"
        + json.dumps(
            {
                "Name": "glia",
                "Service": "glia",
                "State": "running",
                "Health": "healthy",
            }
        )
    )
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0, stdout=ndjson)
        result = runner.invoke(app, ["status"])
    assert result.exit_code == EXIT_OK, result.output
    args, _ = m_run.call_args
    assert args[0][:4] == ["docker", "compose", "ps", "--format"]
    assert "broker" in result.stdout
    assert "glia" in result.stdout


def test_status_empty_says_not_running():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0, stdout="")
        result = runner.invoke(app, ["status"])
    assert result.exit_code == EXIT_OK, result.output
    assert "not running" in result.stdout.lower()


# ---------------------------------------------------------------------------
# ``hive logs``
# ---------------------------------------------------------------------------


def test_logs_broker_default_flags():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["logs", "broker"])
    assert result.exit_code == EXIT_OK, result.output
    args, _ = m_run.call_args
    assert args[0] == [
        "docker",
        "compose",
        "logs",
        "--tail",
        "100",
        "--follow",
        "broker",
    ]


def test_logs_rejects_unknown_service():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        result = runner.invoke(app, ["logs", "notaservice"])
    assert result.exit_code == EXIT_USAGE
    assert m_run.call_count == 0
    err = result.stderr.lower()
    assert "broker" in err and "glia" in err


def test_logs_no_follow_omits_follow_flag():
    runner = _runner()
    with patch("tools.hive_cli.subprocess.run") as m_run:
        m_run.return_value = _completed(0)
        result = runner.invoke(app, ["logs", "broker", "--no-follow"])
    assert result.exit_code == EXIT_OK, result.output
    args, _ = m_run.call_args
    argv = args[0]
    assert "--follow" not in argv
    # Sanity: the compose `logs` command is still constructed normally.
    assert argv[:3] == ["docker", "compose", "logs"]
    assert "broker" in argv
