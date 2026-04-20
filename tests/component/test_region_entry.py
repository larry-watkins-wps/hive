"""Component tests for ``python -m region_template`` entry point.

Plan §Task 3.16 — boots the region runtime as a subprocess against a real
``eclipse-mosquitto:2`` container, asserts a heartbeat envelope appears on
``hive/system/heartbeat/<region>`` within 10 s, signals a graceful
shutdown, and asserts exit code 0.

Windows caveat: POSIX ``SIGTERM`` is not a real Windows signal — sending
it via :meth:`subprocess.Popen.send_signal` kills the process abruptly
with no chance to run the graceful-shutdown path. On Windows we therefore
use ``CTRL_BREAK_EVENT`` (requires ``CREATE_NEW_PROCESS_GROUP`` on spawn)
which Python translates to SIGBREAK inside the child. ``__main__`` installs
a :func:`signal.signal` handler for SIGBREAK that sets the shutdown event
via :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`. On POSIX we
send ``SIGTERM`` directly. Both paths should end in exit code 0.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import docker
import pytest
from ruamel.yaml import YAML
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from region_template.config_loader import MqttConfig
from region_template.mqtt_client import MqttClient
from shared.message_envelope import Envelope

# ---------------------------------------------------------------------------
# Docker guard + markers
# ---------------------------------------------------------------------------


def _docker_reachable() -> bool:
    try:
        client = docker.from_env()
        return bool(client.ping())
    except Exception:
        return False


pytestmark = [
    pytest.mark.component,
    pytest.mark.skipif(
        not _docker_reachable(),
        reason="Docker is not reachable; component tests require a local daemon",
    ),
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CONFIG = REPO_ROOT / "tests" / "fixtures" / "minimal_region" / "config.yaml"
HEARTBEAT_WAIT_S = 10.0
SHUTDOWN_WAIT_S = 10.0
# argparse's parser.error() always exits with this code.
_ARGPARSE_ERROR_EXIT = 2

_MOSQUITTO_CONF = """\
listener 1883 0.0.0.0
allow_anonymous true
persistence false
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_runtime_config(
    tmp_path: Path, broker_host: str, broker_port: int
) -> Path:
    """Copy the minimal fixture config into ``tmp_path``, patching MQTT.

    testcontainers assigns a dynamic host port per session, so we rewrite
    ``mqtt.broker_host`` / ``mqtt.broker_port`` with the real values at
    test time.
    """
    yaml = YAML(typ="safe")
    with FIXTURE_CONFIG.open("r", encoding="utf-8") as f:
        data = yaml.load(f)
    data.setdefault("mqtt", {})
    data["mqtt"]["broker_host"] = broker_host
    data["mqtt"]["broker_port"] = int(broker_port)

    out = tmp_path / "config.yaml"
    with out.open("w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mosquitto_container(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, int]]:
    """Yield ``(host, port)`` for a running mosquitto container."""
    conf_dir = tmp_path_factory.mktemp("mosquitto_conf_entry")
    conf_file = conf_dir / "mosquitto.conf"
    conf_file.write_text(_MOSQUITTO_CONF, encoding="utf-8")

    host_port = _free_port()
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_bind_ports(1883, host_port)
        .with_volume_mapping(str(conf_dir), "/mosquitto/config", "ro")
    )
    container.start()
    try:
        wait_for_logs(container, "mosquitto version", timeout=30)
        host = container.get_container_host_ip()
        yield (host, host_port)
    finally:
        container.stop()


@contextlib.asynccontextmanager
async def _heartbeat_listener(
    host: str, port: int, region_name: str
) -> AsyncIterator[list[Envelope]]:
    """Subscribe to a region's heartbeat topic; collect envelopes in a list.

    The returned list is mutated in place as heartbeats arrive; tests poll
    ``len(received)`` or await a sentinel event.
    """
    cfg = MqttConfig(
        broker_host=host,
        broker_port=port,
        keepalive_s=30,
        max_connect_attempts=5,
        reconnect_give_up_s=30,
        password_env=None,
    )
    received: list[Envelope] = []

    async def handler(env: Envelope) -> None:
        received.append(env)

    client = MqttClient(cfg, region_name="probe")
    await client.__aenter__()
    run_task = asyncio.create_task(client.run())
    try:
        await client.subscribe(
            f"hive/system/heartbeat/{region_name}", handler, qos=1
        )
        # Small pause so the SUBSCRIBE is on the broker before the
        # subprocess begins publishing.
        await asyncio.sleep(0.3)
        yield received
    finally:
        await client.__aexit__(None, None, None)
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await run_task


def _spawn_entry(
    config_path: Path, extra_env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Launch ``python -m region_template --config <path>`` as a subprocess.

    On Windows we spawn in a new process group so ``CTRL_BREAK_EVENT`` can
    be delivered for graceful shutdown. The subprocess inherits the current
    environment (+ any ``extra_env`` overrides) so ``ANTHROPIC_API_KEY``
    and friends reach the child.
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    return subprocess.Popen(
        [sys.executable, "-m", "region_template", "--config", str(config_path)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def _signal_shutdown(proc: subprocess.Popen[bytes]) -> None:
    """Send the platform-appropriate graceful-shutdown signal to ``proc``."""
    if sys.platform == "win32":
        # CTRL_BREAK_EVENT propagates to the process group; Python
        # translates it into SIGBREAK, which __main__ has a handler for.
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    else:
        proc.send_signal(signal.SIGTERM)


async def _await_heartbeat(received: list[Envelope], timeout: float) -> Envelope:
    """Poll ``received`` until at least one envelope appears or timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not received:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(
                f"no heartbeat observed within {timeout:.0f}s"
            )
        await asyncio.sleep(0.1)
    return received[0]


def _wait_for_exit(
    proc: subprocess.Popen[bytes], timeout: float
) -> tuple[int | None, bytes, bytes]:
    """Wait up to ``timeout`` for the subprocess; return (code, out, err).

    On timeout we escalate with ``terminate()`` + ``kill()`` so the test
    process doesn't hang; the returncode is returned as-is so the caller
    can assert graceful exit.
    """
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            out, err = proc.communicate(timeout=2.0)
            return (proc.returncode, out or b"", err or b"")
        proc.kill()
        out, err = proc.communicate()
    return (proc.returncode, out or b"", err or b"")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegionEntrypointBoot:
    """``python -m region_template --config <yaml>`` boots end-to-end."""

    async def test_boot_heartbeat_and_graceful_shutdown(
        self,
        mosquitto_container: tuple[str, int],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        host, port = mosquitto_container
        # LlmAdapter asserts ANTHROPIC_API_KEY is present at bootstrap; a
        # dummy value is enough because no LLM call happens before the
        # heartbeat fires.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
        config_path = _write_runtime_config(tmp_path, host, port)
        region_name = "test_region"

        async with _heartbeat_listener(host, port, region_name) as received:
            proc = _spawn_entry(
                config_path,
                extra_env={"ANTHROPIC_API_KEY": "sk-test-dummy"},
            )
            try:
                envelope = await _await_heartbeat(received, HEARTBEAT_WAIT_S)
            except TimeoutError:
                # Drain diagnostics from the subprocess so the test failure
                # message includes whatever the child actually logged.
                _signal_shutdown(proc)
                code, out, err = _wait_for_exit(proc, 5.0)
                pytest.fail(
                    f"no heartbeat within {HEARTBEAT_WAIT_S:.0f}s; "
                    f"exit={code}\nstdout={out!r}\nstderr={err!r}"
                )

            # Assert the envelope is well-formed and from the right region.
            assert envelope.source_region == region_name
            assert envelope.topic == f"hive/system/heartbeat/{region_name}"
            assert envelope.payload.content_type == "application/json"
            data = envelope.payload.data
            assert isinstance(data, dict)
            assert data.get("region") == region_name
            assert data.get("status") in {"boot", "wake"}

            # Graceful shutdown.
            _signal_shutdown(proc)
            code, out, err = _wait_for_exit(proc, SHUTDOWN_WAIT_S)

        # Assert clean exit. On Windows, CTRL_BREAK_EVENT is translated by
        # Python into SIGBREAK which our _main loop catches via a
        # KeyboardInterrupt fallback; the resulting exit should still be 0.
        assert code == 0, (
            f"non-zero exit {code} from region subprocess\n"
            f"stdout={out.decode(errors='replace')}\n"
            f"stderr={err.decode(errors='replace')}"
        )


class TestRegionEntrypointHelp:
    """``--help`` prints usage cleanly without touching the broker."""

    def test_help_runs_without_error(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "region_template", "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert b"--config" in result.stdout
        assert b"HIVE_REGION" in result.stdout


class TestRegionEntrypointMissingConfig:
    """Missing config + no HIVE_REGION → argparse usage error (exit 2)."""

    def test_no_config_no_env_is_argparse_error(self) -> None:
        env = dict(os.environ)
        env.pop("HIVE_REGION", None)
        result = subprocess.run(
            [sys.executable, "-m", "region_template"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            check=False,
            timeout=15,
        )
        # argparse's parser.error() exits 2; our spec also maps ConfigError
        # to 2, but here the error comes from argparse itself.
        assert result.returncode == _ARGPARSE_ERROR_EXIT
        assert b"--config is required" in result.stderr


