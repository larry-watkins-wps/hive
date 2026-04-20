"""Unit tests for region_template.mqtt_client.

These tests drive the client via its public API — either the real
:class:`region_template.mqtt_client.MqttClient` or the
:class:`tests.fakes.mqtt.FakeMqttClient`, which implement the same async-
context-manager + publish/subscribe/unsubscribe contract.

Retained-flag semantics are a broker concern and are covered in
``tests/component/test_mqtt_real_broker.py`` — not here.

Spec: §B.9 (connection/LWT), §B.10 (reconnect), §B.11 (session), §B.12
(envelope enrichment), §B.14 (failure modes).
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

import region_template.mqtt_client as mqtt_client_mod
from region_template.config_loader import MqttConfig
from region_template.errors import ConnectionError as HiveConnectionError
from region_template.mqtt_client import MqttClient
from shared.message_envelope import Envelope
from tests.fakes.mqtt import FakeMqttClient

# Named constants for tests (PLR2004).
_TEST_BROKER_PORT = 18830
_TEST_MAX_ATTEMPTS = 3
_EXPECTED_SESSION_EXPIRY_S = 3600

# ---------------------------------------------------------------------------
# FakeMqttClient tests — validate the fake's contract, since the real unit
# tests depend on it behaving like the real client for publish/subscribe.
# ---------------------------------------------------------------------------


class TestFakeMqttClient:
    async def test_publish_enriches_envelope(self) -> None:
        fake = FakeMqttClient(region_name="amygdala")
        async with fake:
            await fake.publish(
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.7},
                retain=True,
            )

        assert len(fake.published) == 1
        topic, env, qos, retain = fake.published[0]
        assert topic == "hive/modulator/cortisol"
        assert env.source_region == "amygdala"
        assert env.id  # uuid auto-filled
        assert env.timestamp  # ISO-8601 auto-filled
        assert env.payload.content_type == "application/hive+modulator"
        assert env.payload.data == {"level": 0.7}
        assert qos == 1
        assert retain is True

    async def test_subscribe_and_inject_dispatches_to_handler(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with fake:
            await fake.subscribe("hive/modulator/cortisol", handler)
            env = Envelope.new(
                source_region="amygdala",
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.7},
            )
            await fake.inject("hive/modulator/cortisol", env)

        assert len(received) == 1
        assert received[0].source_region == "amygdala"
        assert received[0].payload.data == {"level": 0.7}

    async def test_inject_matches_wildcard_filters(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        received: list[str] = []

        async def handler(env: Envelope) -> None:
            received.append(env.topic)

        async with fake:
            await fake.subscribe("hive/system/heartbeat/+", handler)
            env = Envelope.new(
                source_region="amygdala",
                topic="hive/system/heartbeat/amygdala",
                content_type="application/json",
                data={"ok": True},
            )
            await fake.inject("hive/system/heartbeat/amygdala", env)

        assert received == ["hive/system/heartbeat/amygdala"]

    async def test_unsubscribe_stops_delivery(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with fake:
            await fake.subscribe("hive/rhythm/gamma", handler)
            await fake.unsubscribe("hive/rhythm/gamma", handler)
            env = Envelope.new(
                source_region="thalamus",
                topic="hive/rhythm/gamma",
                content_type="application/json",
                data={"tick": 1},
            )
            await fake.inject("hive/rhythm/gamma", env)

        assert received == []

    async def test_unsubscribe_all_when_handler_is_none(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        received_a: list[Envelope] = []
        received_b: list[Envelope] = []

        async def ha(env: Envelope) -> None:
            received_a.append(env)

        async def hb(env: Envelope) -> None:
            received_b.append(env)

        async with fake:
            await fake.subscribe("hive/rhythm/gamma", ha)
            await fake.subscribe("hive/rhythm/gamma", hb)
            await fake.unsubscribe("hive/rhythm/gamma")  # handler=None
            await fake.inject(
                "hive/rhythm/gamma",
                Envelope.new(
                    source_region="thalamus",
                    topic="hive/rhythm/gamma",
                    content_type="application/json",
                    data={"tick": 1},
                ),
            )

        assert received_a == []
        assert received_b == []

    async def test_unsubscribe_unknown_filter_is_noop(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        async with fake:
            # Must not raise.
            await fake.unsubscribe("hive/nothing/here")

    async def test_multiple_handlers_all_receive(self) -> None:
        fake = FakeMqttClient(region_name="test_region")
        a: list[Envelope] = []
        b: list[Envelope] = []

        async def ha(env: Envelope) -> None:
            a.append(env)

        async def hb(env: Envelope) -> None:
            b.append(env)

        async with fake:
            await fake.subscribe("hive/rhythm/gamma", ha)
            await fake.subscribe("hive/rhythm/gamma", hb)
            env = Envelope.new(
                source_region="thalamus",
                topic="hive/rhythm/gamma",
                content_type="application/json",
                data={"tick": 1},
            )
            await fake.inject("hive/rhythm/gamma", env)

        assert len(a) == 1
        assert len(b) == 1


# ---------------------------------------------------------------------------
# MqttClient tests — exercise the real class with aiomqtt monkey-patched.
#
# The real client delegates connect/publish/subscribe to aiomqtt.Client. We
# monkey-patch aiomqtt.Client with a stub to keep these tests hermetic; the
# component tests in tests/component/ validate the real wiring.
# ---------------------------------------------------------------------------


class _StubAiomqttClient:
    """Minimal stand-in for ``aiomqtt.Client`` used by unit tests.

    Records publish/subscribe/unsubscribe calls; supports an injectable message
    queue so tests can exercise the ``run`` dispatch loop without a broker.
    """

    instances: list[_StubAiomqttClient] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.unsubscribed: list[str] = []
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self.aenter_calls = 0
        self.aexit_calls = 0
        _StubAiomqttClient.instances.append(self)

    async def __aenter__(self) -> _StubAiomqttClient:
        self.aenter_calls += 1
        return self

    async def __aexit__(self, *a: object) -> None:
        self.aexit_calls += 1

    async def publish(
        self,
        topic: str,
        payload: bytes,
        qos: int = 0,
        retain: bool = False,
        **kwargs: object,
    ) -> None:
        self.published.append((topic, payload, qos, retain))

    async def subscribe(self, topic: str, qos: int = 0, **kwargs: object) -> None:
        self.subscribed.append((topic, qos))

    async def unsubscribe(self, topic: str, **kwargs: object) -> None:
        self.unsubscribed.append(topic)

    @property
    def messages(self) -> asyncio.Queue:
        return self._message_queue


@pytest.fixture
def stub_aiomqtt(monkeypatch: pytest.MonkeyPatch) -> type[_StubAiomqttClient]:
    """Monkey-patch ``aiomqtt.Client`` with the stub.

    Yields the stub class so tests can inspect ``instances``.
    """
    _StubAiomqttClient.instances = []
    monkeypatch.setattr(mqtt_client_mod.aiomqtt, "Client", _StubAiomqttClient)
    return _StubAiomqttClient


def _cfg(**overrides: object) -> MqttConfig:
    base: dict = {
        "broker_host": "localhost",
        "broker_port": 1883,
        "keepalive_s": 30,
        "max_connect_attempts": 3,
        "reconnect_give_up_s": 10,
        "password_env": None,
    }
    base.update(overrides)
    return MqttConfig(**base)


class TestMqttClientConnect:
    async def test_connect_constructs_client_with_config_and_lwt(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg(broker_host="broker.example", broker_port=_TEST_BROKER_PORT)
        client = MqttClient(cfg, region_name="amygdala")

        async with client:
            pass

        assert len(stub_aiomqtt.instances) == 1
        stub = stub_aiomqtt.instances[0]
        kw = stub.init_kwargs
        assert kw["hostname"] == "broker.example"
        assert kw["port"] == _TEST_BROKER_PORT
        assert kw["identifier"] == "hive-amygdala"
        # MQTT v5 uses clean_start+properties; see §B.11.
        assert kw["clean_start"] is False
        assert kw["protocol"] == mqtt_client_mod.ProtocolVersion.V5
        # Session-expiry property retains QoS-1 queue for 1h.
        assert kw["properties"].SessionExpiryInterval == _EXPECTED_SESSION_EXPIRY_S
        # LWT on the heartbeat topic, retained, qos=1
        will = kw["will"]
        assert will.topic == "hive/system/heartbeat/amygdala"
        assert will.retain is True
        assert will.qos == 1
        # LWT payload is an envelope with status=dead
        lwt_env = json.loads(will.payload)
        assert lwt_env["source_region"] == "amygdala"
        assert lwt_env["payload"]["data"]["status"] == "dead"

    async def test_connect_resolves_password_from_env(
        self,
        stub_aiomqtt: type[_StubAiomqttClient],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MQTT_PASSWD_TEST", "s3cret")
        cfg = _cfg(password_env="MQTT_PASSWD_TEST")
        async with MqttClient(cfg, region_name="test_region"):
            pass
        assert stub_aiomqtt.instances[0].init_kwargs["password"] == "s3cret"

    async def test_connect_retries_then_gives_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After max_connect_attempts, raise HiveConnectionError."""
        call_count = {"n": 0}

        class _FailingClient:
            def __init__(self, *a: object, **kw: object) -> None:
                pass

            async def __aenter__(self) -> _FailingClient:
                call_count["n"] += 1
                raise mqtt_client_mod.aiomqtt.MqttError("boom")

            async def __aexit__(self, *a: object) -> None:
                return None

        monkeypatch.setattr(mqtt_client_mod.aiomqtt, "Client", _FailingClient)
        # Stub sleep so the test completes quickly.
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(mqtt_client_mod.asyncio, "sleep", fake_sleep)

        cfg = _cfg(max_connect_attempts=_TEST_MAX_ATTEMPTS)
        client = MqttClient(cfg, region_name="test_region")
        with pytest.raises(HiveConnectionError):
            await client.connect()

        assert call_count["n"] == _TEST_MAX_ATTEMPTS
        # Exp backoff capped at 30: 1, 2, 4 for three attempts.
        assert sleeps == [1, 2, 4]


class TestMqttClientPublish:
    async def test_publish_enriches_envelope_and_encodes_bytes(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg()
        async with MqttClient(cfg, region_name="amygdala") as client:
            await client.publish(
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.7},
                qos=0,
                retain=True,
            )

        stub = stub_aiomqtt.instances[0]
        assert len(stub.published) == 1
        topic, payload, qos, retain = stub.published[0]
        assert topic == "hive/modulator/cortisol"
        assert qos == 0
        assert retain is True

        env = Envelope.from_json(payload)
        assert env.source_region == "amygdala"
        assert env.topic == "hive/modulator/cortisol"
        assert env.payload.data == {"level": 0.7}

    async def test_publish_propagates_correlation_id(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg()
        async with MqttClient(cfg, region_name="test_region") as client:
            await client.publish(
                topic="hive/cognitive/prefrontal/plan",
                content_type="text/plain",
                data="plan text",
                correlation_id="corr-123",
            )
        stub = stub_aiomqtt.instances[0]
        env = Envelope.from_json(stub.published[0][1])
        assert env.correlation_id == "corr-123"


class TestMqttClientSubscribe:
    async def test_subscribe_registers_filter_and_dispatches(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg()
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with MqttClient(cfg, region_name="test_region") as client:
            await client.subscribe("hive/modulator/cortisol", handler)

            # Inject a message via the stub's queue; call _dispatch directly.
            env = Envelope.new(
                source_region="amygdala",
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.7},
            )
            await client._dispatch("hive/modulator/cortisol", env.to_json())

        assert len(received) == 1
        assert received[0].payload.data == {"level": 0.7}

        stub = stub_aiomqtt.instances[0]
        assert ("hive/modulator/cortisol", 1) in stub.subscribed

    async def test_unsubscribe_stops_dispatch(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg()
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with MqttClient(cfg, region_name="test_region") as client:
            await client.subscribe("hive/rhythm/gamma", handler)
            await client.unsubscribe("hive/rhythm/gamma", handler)
            env = Envelope.new(
                source_region="thalamus",
                topic="hive/rhythm/gamma",
                content_type="application/json",
                data={"tick": 1},
            )
            await client._dispatch("hive/rhythm/gamma", env.to_json())

        assert received == []

    async def test_malformed_envelope_drops_and_publishes_poison(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        cfg = _cfg()
        received: list[Envelope] = []

        async def handler(env: Envelope) -> None:
            received.append(env)

        async with MqttClient(cfg, region_name="test_region") as client:
            await client.subscribe("hive/rhythm/gamma", handler)
            # Malformed JSON
            await client._dispatch("hive/rhythm/gamma", b"{{{not json")

        assert received == []
        # Metacog poison_message published
        stub = stub_aiomqtt.instances[0]
        topics = [t for t, *_ in stub.published]
        assert "hive/metacognition/error/detected" in topics
        poison_env = Envelope.from_json(
            next(p for t, p, *_ in stub.published if t == "hive/metacognition/error/detected")
        )
        assert poison_env.payload.data["kind"] == "poison_message"


class TestMqttClientQueueOverflow:
    async def test_publish_when_disconnected_enqueues_out_queue(
        self, stub_aiomqtt: type[_StubAiomqttClient]
    ) -> None:
        """When the client has no active aiomqtt connection, publish() should
        enqueue to _out_queue rather than raise."""
        cfg = _cfg()
        client = MqttClient(cfg, region_name="test_region")
        # No __aenter__: _client is None.
        await client.publish(
            topic="hive/rhythm/gamma",
            content_type="application/json",
            data={"x": 1},
            qos=0,
        )
        assert client._out_queue.qsize() == 1

    async def test_queue_full_drops_and_logs(
        self, stub_aiomqtt: type[_StubAiomqttClient], caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.ERROR)
        cfg = _cfg()
        client = MqttClient(cfg, region_name="test_region")
        # Fill the out_queue to capacity manually.
        maxsize = client._out_queue.maxsize
        for _ in range(maxsize):
            client._out_queue.put_nowait(
                Envelope.new(
                    source_region="x",
                    topic="hive/rhythm/gamma",
                    content_type="application/json",
                    data={"x": 0},
                )
            )
        # Next publish must drop, not hang.
        await client.publish(
            topic="hive/rhythm/gamma",
            content_type="application/json",
            data={"x": 999},
        )
        # Queue size stays at maxsize (not exceeded).
        assert client._out_queue.qsize() == maxsize
