"""Integration tests for MQTT ACL enforcement (spec §B.6, Task 9.4).

Spins up an eclipse-mosquitto:2 container with:
  - ``allow_anonymous false``
  - a ``passwd`` file with hashed credentials for 4 users
  - an ``acl.conf`` rendered by :class:`glia.acl_manager.AclManager` from
    the real ``bus/acl_templates/`` files, with a synthetic ``hardware_bridge``
    user appended.

Four assertions:
1. amygdala CANNOT subscribe to ``hive/hardware/mic``  (detected via missed delivery)
2. amygdala CANNOT publish to ``hive/self/identity``    (mpfc subscriber sees nothing)
3. auditory_cortex CAN subscribe to ``hive/hardware/mic``  (receives from bridge)
4. medial_prefrontal_cortex CAN publish to ``hive/self/identity``  (reader receives it)

The "observe the negative" pattern is used for denial tests because mosquitto 2.x
logs ``ACL denying access`` but does NOT disconnect the client on subscribe ACL
failure — it just silently refuses delivery.  For QoS-0 publish denials the message
is also silently dropped.

Windows notes:
  - Selector event-loop policy forced via module-level ``event_loop_policy`` fixture.
  - Testcontainers Ryuk disabled at module import via ``os.environ.setdefault``.
  - ``mosquitto_passwd`` is run inside a short-lived container (docker SDK exec).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import docker
import pytest

# Disable Ryuk before any testcontainers import (Windows Docker Desktop probe
# on port 8080 fails; our fixtures always call container.stop() in finally).
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# ---------------------------------------------------------------------------
# Optional-dependency guards (fail at collection if either is absent)
# ---------------------------------------------------------------------------
pytest.importorskip("aiomqtt")
pytest.importorskip("testcontainers")

import aiomqtt  # noqa: E402  (after importorskip)
from testcontainers.core.container import DockerContainer  # noqa: E402
from testcontainers.core.waiting_utils import wait_for_logs  # noqa: E402

# ---------------------------------------------------------------------------
# Test markers
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "bus" / "acl_templates"

# Password for every test user: "test"  (simple; only used inside ephemeral
# containers that are never exposed to any network).
_TEST_PASSWORD = "test"

# Users that need passwd entries + ACL entries
_USERS = ["amygdala", "auditory_cortex", "medial_prefrontal_cortex", "hardware_bridge"]

# The extra ACL block we append so the test has an authorised writer for
# hive/hardware/mic (no real region writes this — it comes from a hardware bridge).
_HARDWARE_BRIDGE_ACL_BLOCK = "\nuser hardware_bridge\ntopic write hive/hardware/mic\n"

# Mosquitto config template — references /mosquitto/config/ (the bind-mount target).
_MOSQUITTO_CONF = """\
listener 1883 0.0.0.0
protocol mqtt
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/acl.conf
persistence false
log_dest stdout
"""


# ---------------------------------------------------------------------------
# Windows event-loop policy (must be session-scoped so pytest-asyncio picks it up)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Force selector loop on Windows; aiomqtt needs add_reader/add_writer."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Docker availability guard (skip early rather than fail confusingly)
# ---------------------------------------------------------------------------


def _docker_reachable() -> bool:
    try:
        c = docker.from_env()
        return bool(c.ping())
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Helpers — passwd file generation
# ---------------------------------------------------------------------------


def _make_passwd_file(conf_dir: Path) -> None:
    """Generate a mosquitto passwd file for all test users.

    Runs ``mosquitto_passwd`` inside an ephemeral ``eclipse-mosquitto:2``
    container with *conf_dir* bind-mounted at ``/data``.  Uses ``subprocess``
    rather than the docker SDK exec API for simplicity on Windows.

    The generated file is written to ``conf_dir / "passwd"``.
    """
    passwd_path = conf_dir / "passwd"
    # On Windows, Docker Desktop needs forward slashes in the bind-mount host path.
    host_dir = str(conf_dir).replace("\\", "/")

    # Build the shell command: create the file then add each user with -b flag.
    # -c creates (or overwrites) the file; subsequent users use just -b.
    user_cmds = []
    for i, user in enumerate(_USERS):
        flag = "-c" if i == 0 else ""
        # mosquitto_passwd [-c] -b <passwordfile> <username> <password>
        if flag:
            user_cmds.append(
                f"mosquitto_passwd {flag} -b /data/passwd {user} {_TEST_PASSWORD}"
            )
        else:
            user_cmds.append(
                f"mosquitto_passwd -b /data/passwd {user} {_TEST_PASSWORD}"
            )
    # chmod 644 so mosquitto (uid 1883) can read the file from the bind-mount;
    # Docker Desktop on Windows mounts files owned by root with restricted modes.
    user_cmds.append("chmod 644 /data/passwd")
    shell_cmd = " && ".join(user_cmds)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{host_dir}:/data",
            "eclipse-mosquitto:2",
            "sh",
            "-c",
            shell_cmd,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"mosquitto_passwd container failed (rc={result.returncode}):\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    if not passwd_path.exists():
        raise RuntimeError(
            f"mosquitto_passwd ran but {passwd_path} was not created; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Session-scoped fixture: broker with ACLs
# ---------------------------------------------------------------------------


class _BrokerInfo:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def __repr__(self) -> str:
        return f"<BrokerInfo {self.host}:{self.port}>"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def broker_with_acls(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[_BrokerInfo]:
    """Start mosquitto with auth + ACLs rendered from real bus/acl_templates/.

    Module-scoped: all four tests in this file share one broker instance.

    Skips gracefully when Docker is unreachable.
    """
    if not _docker_reachable():
        pytest.skip("Docker is not reachable; ACL enforcement tests require Docker")

    conf_dir = tmp_path_factory.mktemp("acl_conf")

    # ---- 1. Generate passwd file -------------------------------------------
    _make_passwd_file(conf_dir)

    # ---- 2. Render ACL via AclManager ---------------------------------------
    from glia.acl_manager import AclManager  # noqa: PLC0415
    from glia.registry import RegionRegistry  # noqa: PLC0415

    registry = RegionRegistry.load()
    mgr = AclManager(
        registry,
        template_dir=TEMPLATE_DIR,
        bus_dir=conf_dir,
        reload_sleep_s=0.0,
    )
    acl_body = mgr.render_all(
        regions=["amygdala", "auditory_cortex", "medial_prefrontal_cortex"]
    )
    # Append synthetic hardware_bridge block so tests have an authorised writer
    # for hive/hardware/mic (no real region in the 14-region set writes it).
    acl_body += _HARDWARE_BRIDGE_ACL_BLOCK
    (conf_dir / "acl.conf").write_text(acl_body, encoding="utf-8")

    # ---- 3. Write mosquitto.conf -------------------------------------------
    (conf_dir / "mosquitto.conf").write_text(_MOSQUITTO_CONF, encoding="utf-8")

    # ---- 4. Start container -------------------------------------------------
    host_port = _free_port()
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_bind_ports(1883, host_port)
        .with_volume_mapping(str(conf_dir), "/mosquitto/config", "ro")
    )
    try:
        container.start()
        wait_for_logs(container, "mosquitto version", timeout=30)
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            container.stop()
        pytest.skip(f"broker_with_acls container failed to start: {exc}")
        return

    host = container.get_container_host_ip()
    try:
        yield _BrokerInfo(host=host, port=host_port)
    finally:
        with contextlib.suppress(Exception):
            container.stop()


# ---------------------------------------------------------------------------
# Helpers — aiomqtt client factory
# ---------------------------------------------------------------------------


def _client(
    broker: _BrokerInfo,
    username: str,
    identifier: str | None = None,
) -> aiomqtt.Client:
    """Build an aiomqtt.Client for *username* against the test broker."""
    return aiomqtt.Client(
        hostname=broker.host,
        port=broker.port,
        username=username,
        password=_TEST_PASSWORD,
        identifier=identifier or f"{username}-test",
        timeout=10.0,
    )


# ---------------------------------------------------------------------------
# Test 1 — amygdala CANNOT subscribe to hive/hardware/mic
# ---------------------------------------------------------------------------


async def test_amygdala_cannot_subscribe_to_mic(
    broker_with_acls: _BrokerInfo,
) -> None:
    """amygdala subscribes to hive/hardware/mic; hardware_bridge publishes.

    Mosquitto 2.x silently denies the subscription (ACL violation) without
    disconnecting the client.  We verify denial by observing that no message
    arrives within a 2-second window, even though hardware_bridge — which IS
    allowed to publish there — sends a message.
    """
    received: list[aiomqtt.Message] = []

    # Step 1: amygdala subscribes (broker silently denies via ACL).
    async with _client(broker_with_acls, "amygdala", "amygdala-sub-mic") as sub:
        await sub.subscribe("hive/hardware/mic")
        await asyncio.sleep(0.3)  # let SUBACK round-trip

        # Step 2: hardware_bridge publishes to hive/hardware/mic.
        async with _client(
            broker_with_acls, "hardware_bridge", "hw-bridge-pub1"
        ) as pub:
            await pub.publish("hive/hardware/mic", payload=b"audio-frame-1", qos=0)
            await asyncio.sleep(0.2)  # ensure broker processes the publish

        # Step 3: give amygdala subscriber 2 s to (not) receive.
        try:
            msg = await asyncio.wait_for(
                sub.messages.__anext__(), timeout=2.0  # type: ignore[attr-defined]
            )
            received.append(msg)
        except (TimeoutError, aiomqtt.MqttError):
            pass  # expected — ACL denied the subscription

    assert received == [], (
        f"amygdala received message on hive/hardware/mic but should be ACL-denied; "
        f"got: {[bytes(m.payload) for m in received]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — amygdala CANNOT publish to hive/self/identity
# ---------------------------------------------------------------------------


async def test_amygdala_cannot_publish_to_self_identity(
    broker_with_acls: _BrokerInfo,
) -> None:
    """amygdala publishes to hive/self/identity; mpfc subscriber sees nothing.

    medial_prefrontal_cortex has ``topic read hive/self/#`` via _base.j2, so it
    would normally receive anything on that topic.  Since amygdala is NOT allowed
    to publish there (its ACL only permits writing to modulators and specific
    cognitive topics), the broker silently drops the message.
    """
    received: list[aiomqtt.Message] = []

    async with _client(
        broker_with_acls, "medial_prefrontal_cortex", "mpfc-sub-self"
    ) as reader:
        await reader.subscribe("hive/self/identity")
        await asyncio.sleep(0.3)  # SUBACK round-trip

        # amygdala attempts to publish — broker silently drops (ACL denied).
        async with _client(
            broker_with_acls, "amygdala", "amygdala-pub-self"
        ) as pub:
            await pub.publish(
                "hive/self/identity", payload=b"impersonation", qos=0
            )
            await asyncio.sleep(0.2)

        # Give reader 2 s to (not) receive anything.
        try:
            msg = await asyncio.wait_for(
                reader.messages.__anext__(),  # type: ignore[attr-defined]
                timeout=2.0,
            )
            received.append(msg)
        except (TimeoutError, aiomqtt.MqttError):
            pass  # expected

    assert received == [], (
        f"mpfc received message published by amygdala on hive/self/identity, "
        f"but amygdala should be ACL-denied; "
        f"got: {[bytes(m.payload) for m in received]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — auditory_cortex CAN subscribe to hive/hardware/mic
# ---------------------------------------------------------------------------


async def test_auditory_cortex_can_subscribe_to_mic(
    broker_with_acls: _BrokerInfo,
) -> None:
    """auditory_cortex subscribes to hive/hardware/mic; hardware_bridge publishes.

    auditory_cortex.j2 contains ``topic read hive/hardware/mic``, so the broker
    MUST deliver the message.
    """
    received: list[aiomqtt.Message] = []
    event = asyncio.Event()

    async with _client(
        broker_with_acls, "auditory_cortex", "auditory-sub-mic"
    ) as sub:
        await sub.subscribe("hive/hardware/mic")
        await asyncio.sleep(0.3)  # SUBACK round-trip

        async with _client(
            broker_with_acls, "hardware_bridge", "hw-bridge-pub2"
        ) as pub:
            await pub.publish("hive/hardware/mic", payload=b"audio-frame-2", qos=0)

        # Wait up to 3 s for delivery.
        async def _consume() -> None:
            async for msg in sub.messages:
                received.append(msg)
                event.set()
                return

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_consume(), timeout=3.0)

    assert len(received) == 1, (
        f"auditory_cortex should receive 1 message on hive/hardware/mic "
        f"(ACL allows it), but received {len(received)}"
    )
    assert bytes(received[0].payload) == b"audio-frame-2"


# ---------------------------------------------------------------------------
# Test 4 — medial_prefrontal_cortex CAN publish to hive/self/identity
# ---------------------------------------------------------------------------


async def test_mpfc_can_publish_to_self_identity(
    broker_with_acls: _BrokerInfo,
) -> None:
    """mpfc publishes to hive/self/identity; another allowed reader receives it.

    medial_prefrontal_cortex.j2 contains ``topic write hive/self/identity``.
    _base.j2 gives every region ``topic read hive/self/#``, so auditory_cortex
    is also allowed to subscribe and receive.
    """
    received: list[aiomqtt.Message] = []

    # Use auditory_cortex as the reader: _base.j2 grants ``topic read hive/self/#``.
    async with _client(
        broker_with_acls, "auditory_cortex", "auditory-sub-self"
    ) as reader:
        await reader.subscribe("hive/self/identity")
        await asyncio.sleep(0.3)  # SUBACK round-trip

        # mpfc publishes — broker should allow and deliver.
        async with _client(
            broker_with_acls, "medial_prefrontal_cortex", "mpfc-pub-self"
        ) as pub:
            await pub.publish(
                "hive/self/identity",
                payload=b"identity-payload",
                qos=0,
            )

        # Wait up to 3 s for delivery.
        async def _consume() -> None:
            async for msg in reader.messages:
                received.append(msg)
                return

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_consume(), timeout=3.0)

    assert len(received) == 1, (
        f"auditory_cortex should receive mpfc's publish on hive/self/identity "
        f"(ACL allows it), but received {len(received)}"
    )
    assert bytes(received[0].payload) == b"identity-payload"
