"""Component tests for region_template.mqtt_client against real Mosquitto.

Spins up an ephemeral ``eclipse-mosquitto:2`` container via ``testcontainers``
and exercises publish/subscribe + retained-flag semantics per spec §B.5.

Retained topics in the spec (§B.5):
- Modulators, Self, Interoception, Attention, System metrics, Heartbeat LWT.

This test verifies:
- A retained publish on ``hive/modulator/cortisol`` is delivered to a *fresh*
  subscriber (arriving after the publish) immediately on SUBSCRIBE.
- A non-retained publish on ``hive/rhythm/gamma`` is NOT delivered to a
  fresh subscriber.

The test is marked ``@pytest.mark.component`` and skipped when Docker is
unreachable (no daemon, no socket, etc.).
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator, Iterator

import docker
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from region_template.config_loader import MqttConfig
from region_template.mqtt_client import MqttClient
from shared.message_envelope import Envelope

# ---------------------------------------------------------------------------
# Docker availability guard
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
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# Mosquitto config that disables auth (v2 requires explicit allow_anonymous).
_MOSQUITTO_CONF = """\
listener 1883 0.0.0.0
allow_anonymous true
persistence false
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mosquitto_container(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, int]]:
    """Yield (host, port) for a running mosquitto container.

    Module-scoped: multiple tests in this file share a single broker.
    """
    conf_dir = tmp_path_factory.mktemp("mosquitto_conf")
    conf_file = conf_dir / "mosquitto.conf"
    conf_file.write_text(_MOSQUITTO_CONF, encoding="utf-8")

    host_port = _free_port()
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_bind_ports(1883, host_port)
        .with_volume_mapping(
            str(conf_dir), "/mosquitto/config", "ro"
        )
    )
    container.start()
    try:
        wait_for_logs(container, "mosquitto version", timeout=30)
        host = container.get_container_host_ip()
        yield (host, host_port)
    finally:
        container.stop()


def _cfg(host: str, port: int) -> MqttConfig:
    return MqttConfig(
        broker_host=host,
        broker_port=port,
        keepalive_s=30,
        max_connect_attempts=5,
        reconnect_give_up_s=30,
        password_env=None,
    )


@contextlib.asynccontextmanager
async def _running_client(
    cfg: MqttConfig, region: str
) -> AsyncIterator[tuple[MqttClient, asyncio.Task]]:
    """Open a client, start its run loop, tear both down cleanly."""
    client = MqttClient(cfg, region_name=region)
    await client.__aenter__()
    run_task = asyncio.create_task(client.run())
    try:
        yield client, run_task
    finally:
        await client.__aexit__(None, None, None)
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await run_task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRealBrokerPublishSubscribe:
    async def test_publish_and_subscribe_delivers(
        self, mosquitto_container: tuple[str, int]
    ) -> None:
        host, port = mosquitto_container
        cfg = _cfg(host, port)

        received: list[Envelope] = []
        event = asyncio.Event()

        async def handler(env: Envelope) -> None:
            received.append(env)
            event.set()

        async with _running_client(cfg, "amygdala") as (sub, _):
            await sub.subscribe("hive/rhythm/gamma", handler, qos=0)
            # Small yield so SUBSCRIBE completes before we publish.
            await asyncio.sleep(0.2)

            async with _running_client(cfg, "thalamus") as (pub, _):
                await pub.publish(
                    topic="hive/rhythm/gamma",
                    content_type="application/json",
                    data={"tick": 42},
                    qos=0,
                    retain=False,
                )
                await asyncio.wait_for(event.wait(), timeout=5.0)

        assert len(received) == 1
        assert received[0].source_region == "thalamus"
        assert received[0].payload.data == {"tick": 42}


class TestRetainedSemantics:
    async def test_retained_modulator_delivered_to_fresh_subscriber(
        self, mosquitto_container: tuple[str, int]
    ) -> None:
        """§B.5 — retained publish on modulator topic persists in the broker.

        A subscriber that connects *after* the publish should receive the
        retained envelope immediately on SUBSCRIBE.
        """
        host, port = mosquitto_container
        cfg = _cfg(host, port)

        # 1. Publish retained, then disconnect entirely.
        async with _running_client(cfg, "amygdala") as (pub, _):
            await pub.publish(
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.77},
                qos=0,
                retain=True,
            )
            await asyncio.sleep(0.2)

        # 2. Fresh subscriber (different client id) subscribes AFTER publish.
        received: list[Envelope] = []
        event = asyncio.Event()

        async def handler(env: Envelope) -> None:
            received.append(env)
            event.set()

        async with _running_client(cfg, "thalamus") as (sub, _):
            await sub.subscribe("hive/modulator/cortisol", handler, qos=0)
            # The broker should deliver the retained message immediately.
            await asyncio.wait_for(event.wait(), timeout=5.0)

        assert len(received) == 1
        assert received[0].payload.data == {"level": 0.77}
        assert received[0].source_region == "amygdala"

        # 3. Cleanup: clear the retained value so re-runs are hermetic.
        #    (§B.5 zero-length retained publish = clear.)
        async with _running_client(cfg, "amygdala") as (cleaner, _):
            await cleaner.clear_retained("hive/modulator/cortisol")
            await asyncio.sleep(0.2)

    async def test_non_retained_rhythm_not_delivered_to_fresh_subscriber(
        self, mosquitto_container: tuple[str, int]
    ) -> None:
        """§B.5 — ``hive/rhythm/gamma`` MUST NOT be retained.

        A subscriber that connects *after* a non-retained publish should NOT
        receive it.
        """
        host, port = mosquitto_container
        cfg = _cfg(host, port)

        # 1. Publish non-retained, then disconnect.
        async with _running_client(cfg, "thalamus") as (pub, _):
            await pub.publish(
                topic="hive/rhythm/gamma",
                content_type="application/json",
                data={"tick": 1},
                qos=0,
                retain=False,
            )
            await asyncio.sleep(0.2)

        # 2. Fresh subscriber — should NOT receive anything.
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with _running_client(cfg, "amygdala") as (sub, _):
            await sub.subscribe("hive/rhythm/gamma", handler, qos=0)
            # Give the broker ample time to (not) deliver.
            await asyncio.sleep(1.0)

        assert received == []
