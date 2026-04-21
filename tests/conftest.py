"""Shared pytest fixtures for the Hive test suite.

Fixtures defined here are available to all nested test directories
(unit/, integration/, component/).  Fixtures that require optional
dependencies (testcontainers, docker) defer all imports inside the
fixture body so that test *collection* never fails when those
dependencies or Docker are absent.

Scope summary
-------------
- ``fake_llm``          — function
- ``fake_mqtt``         — function
- ``tmp_region_dir``    — function
- ``broker_container``  — session
- ``compose_stack``     — function

Do NOT add ``autouse=True`` here.  Do NOT hoist the Windows
``event_loop_policy`` fixture from tests/component/conftest.py —
that is intentionally component-scoped.
"""
from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

# Disable testcontainers Ryuk before any testcontainers import.
# Ryuk is a sidecar that cleans up leaked containers; its startup probe
# expects port 8080 immediately, which fails on some Windows/Docker Desktop
# setups.  Our fixtures always call container.stop() in a finally block.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


# ---------------------------------------------------------------------------
# fake_llm
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> Any:
    """Fresh FakeLlmAdapter with no scripted responses.

    Tests configure it via ``fake_llm.scripted_responses.append(...)`` before
    use.  Call ``fake_llm.assert_all_consumed()`` at end of test if strict
    consumption matters.
    """
    from tests.fakes.llm import FakeLlmAdapter  # noqa: PLC0415

    return FakeLlmAdapter()


# ---------------------------------------------------------------------------
# fake_mqtt
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_mqtt() -> Any:
    """Fresh FakeMqttClient with region_name='test_region'."""
    from tests.fakes.mqtt import FakeMqttClient  # noqa: PLC0415

    return FakeMqttClient(region_name="test_region")


# ---------------------------------------------------------------------------
# tmp_region_dir
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG_YAML = """\
name: test_region
role: "test region for fixtures"
schema_version: 1

llm:
  provider: anthropic
  model: claude-haiku-4-5-20251001

capabilities:
  self_modify: true
  tool_use: none
  vision: false
  audio: false

mqtt:
  password_env: MQTT_PASSWORD_TEST_REGION
"""

_MINIMAL_SUBSCRIPTIONS_YAML = """\
schema_version: 1
subscriptions: []
"""

_MINIMAL_PROMPT_MD = "Test region stub prompt.\n"

_MINIMAL_HANDLERS_INIT = '"""Test region handlers package (stub)."""\n'


@pytest.fixture
def tmp_region_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a minimal on-disk region that ``config_loader.load_config`` accepts.

    Yields the region directory path: ``<tmp_path>/regions/test_region``.

    Layout::

        <tmp_path>/
          regions/
            test_region/
              config.yaml
              prompt.md
              subscriptions.yaml
              handlers/
                __init__.py
              memory/
                ltm/

    The config is deliberately minimal — only the fields required by the
    JSON schema are set; everything else picks up defaults.yaml values.
    """
    region_dir = tmp_path / "regions" / "test_region"
    region_dir.mkdir(parents=True)

    (region_dir / "config.yaml").write_text(_MINIMAL_CONFIG_YAML, encoding="utf-8")
    (region_dir / "prompt.md").write_text(_MINIMAL_PROMPT_MD, encoding="utf-8")
    (region_dir / "subscriptions.yaml").write_text(
        _MINIMAL_SUBSCRIPTIONS_YAML, encoding="utf-8"
    )

    handlers_dir = region_dir / "handlers"
    handlers_dir.mkdir()
    (handlers_dir / "__init__.py").write_text(_MINIMAL_HANDLERS_INIT, encoding="utf-8")

    (region_dir / "memory" / "ltm").mkdir(parents=True)

    yield region_dir


# ---------------------------------------------------------------------------
# broker_container (session-scoped)
# ---------------------------------------------------------------------------

# Mosquitto v2 requires explicit ``allow_anonymous true``; without it the
# broker rejects all connections.
_MOSQUITTO_CONF = """\
listener 1883 0.0.0.0
allow_anonymous true
persistence false
"""


def _free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _BrokerInfo:
    """Simple value-object returned by ``broker_container``."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def __repr__(self) -> str:
        return f"<BrokerInfo {self.host}:{self.port}>"


@pytest.fixture(scope="session")
def broker_container(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[_BrokerInfo]:
    """Session-scoped eclipse-mosquitto:2 testcontainer on an ephemeral port.

    Yields a :class:`_BrokerInfo` with ``.host`` and ``.port``.

    Skipped when:
    - ``testcontainers`` is not installed.
    - Docker is unreachable or the container fails to start.

    Example::

        def test_something(broker_container):
            host, port = broker_container.host, broker_container.port
            ...
    """
    # Defer import so collection doesn't fail without testcontainers installed.
    tc = pytest.importorskip("testcontainers")  # noqa: F841

    try:
        import docker as docker_sdk  # noqa: PLC0415

        client = docker_sdk.from_env()
        if not client.ping():
            pytest.skip("Docker is not reachable; broker_container requires Docker")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker is not reachable: {exc}")

    from testcontainers.core.container import DockerContainer  # noqa: PLC0415
    from testcontainers.core.waiting_utils import wait_for_logs  # noqa: PLC0415

    conf_dir = tmp_path_factory.mktemp("broker_conf")
    conf_file = conf_dir / "mosquitto.conf"
    conf_file.write_text(_MOSQUITTO_CONF, encoding="utf-8")

    host_port = _free_port()
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_bind_ports(1883, host_port)
        .with_volume_mapping(str(conf_dir), "/mosquitto/config", "ro")
    )
    try:
        container.start()
        wait_for_logs(container, "mosquitto version", timeout=30)
        host = container.get_container_host_ip()
        yield _BrokerInfo(host=host, port=host_port)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"broker_container failed to start: {exc}")
        return
    finally:
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            container.stop()


# ---------------------------------------------------------------------------
# compose_stack (function-scoped)
# ---------------------------------------------------------------------------

_COMPOSE_FILE = (
    Path(__file__).parent / "integration" / "compose.test.yaml"
)


class _ComposeStack:
    """Value-object yielded by ``compose_stack``."""

    def __init__(
        self,
        compose_file: Path,
        project_name: str,
        broker_host: str,
        broker_port: int,
    ) -> None:
        self.compose_file = compose_file
        self.project_name = project_name
        self.broker_host = broker_host
        self.broker_port = broker_port

    def __repr__(self) -> str:
        return (
            f"<ComposeStack project={self.project_name!r} "
            f"broker={self.broker_host}:{self.broker_port}>"
        )


@pytest.fixture
def compose_stack() -> Generator[_ComposeStack, None, None]:
    """Bring up the integration docker-compose stack, tear it down on exit.

    Skipped when ``tests/integration/compose.test.yaml`` does not yet exist
    (Task 9.2 will create that file).

    Yields a :class:`_ComposeStack` with:
    - ``.compose_file`` — path to the compose file
    - ``.project_name`` — docker compose project name (``hive_test``)
    - ``.broker_host`` / ``.broker_port`` — where the test broker listens

    Teardown always runs ``docker compose down -v`` regardless of test outcome.
    """
    if not _COMPOSE_FILE.exists():
        pytest.skip("compose.test.yaml not yet available (Task 9.2)")

    project = "hive_test"
    compose_cmd_base = [
        "docker",
        "compose",
        "-f",
        str(_COMPOSE_FILE),
        "-p",
        project,
    ]

    subprocess.run(
        [*compose_cmd_base, "up", "-d"],
        check=True,
    )

    try:
        # Task 9.2 will document the broker port; default MQTT port for now.
        yield _ComposeStack(
            compose_file=_COMPOSE_FILE,
            project_name=project,
            broker_host="127.0.0.1",
            broker_port=1883,
        )
    finally:
        subprocess.run(
            [*compose_cmd_base, "down", "-v"],
            check=False,  # best-effort teardown
        )
