"""SensoryPublisher behaviour: allowlist + serialisation + error wrapping.

aiomqtt.Client is mocked — these are pure-unit tests. Real-broker
round-trip is exercised in the component test (Task 4).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiomqtt
import pytest

from observatory.config import Settings
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from observatory.sensory.publisher import SensoryPublisher
from shared.message_envelope import Envelope


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def envelope() -> Envelope:
    return Envelope.new(
        source_region="observatory.sensory",
        topic="hive/external/perception",
        content_type="application/json",
        data={
            "text": "hi",
            "speaker": "Larry",
            "channel": "observatory.chat",
            "source_modality": "text",
        },
    )


@pytest.mark.asyncio
async def test_publish_allowlisted_topic_serialises_and_calls_client(
    settings: Settings, envelope: Envelope,
) -> None:
    client = MagicMock()
    client.publish = AsyncMock()
    pub = SensoryPublisher(settings)
    pub._client = client  # bypass connect for unit test

    await pub.publish(envelope, qos=1)

    client.publish.assert_awaited_once()
    call_topic, call_payload = client.publish.call_args.args
    assert call_topic == "hive/external/perception"
    # to_json returns bytes — the publisher passes them straight through.
    assert isinstance(call_payload, bytes)
    assert b'"topic": "hive/external/perception"' in call_payload
    assert client.publish.call_args.kwargs["qos"] == 1


@pytest.mark.asyncio
async def test_publish_forbidden_topic_raises(settings: Settings) -> None:
    pub = SensoryPublisher(settings)
    pub._client = MagicMock()  # not used — we should raise before publish

    bad = Envelope.new(
        source_region="observatory.sensory",
        topic="hive/cognitive/pfc/oops",
        content_type="application/json",
        data={"x": 1},
    )
    with pytest.raises(ForbiddenTopicError) as exc_info:
        await pub.publish(bad)
    assert exc_info.value.topic == "hive/cognitive/pfc/oops"


@pytest.mark.asyncio
async def test_publish_wraps_mqtt_error(
    settings: Settings, envelope: Envelope,
) -> None:
    client = MagicMock()
    client.publish = AsyncMock(side_effect=aiomqtt.MqttError("broker unreachable"))
    pub = SensoryPublisher(settings)
    pub._client = client

    with pytest.raises(PublishFailedError) as exc_info:
        await pub.publish(envelope)
    assert isinstance(exc_info.value.cause, aiomqtt.MqttError)
    assert "broker unreachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_publish_without_connect_raises_runtime_error(
    settings: Settings, envelope: Envelope,
) -> None:
    pub = SensoryPublisher(settings)
    # never set _client
    with pytest.raises(RuntimeError, match="connect"):
        await pub.publish(envelope)
