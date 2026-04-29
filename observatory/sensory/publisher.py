"""SensoryPublisher — long-lived aiomqtt client with allowlist enforcement.

Lifecycle:
  - constructed once per FastAPI app (in `service.py::lifespan`)
  - `connect()` opens an aiomqtt.Client connection; called in `lifespan`
  - `publish(envelope, qos=...)` validates allowlist + sends bytes
  - `disconnect()` closes the connection cleanly on app shutdown

The aiomqtt connection is established eagerly at startup so the first
chat publish doesn't pay a connection-handshake latency. A failed
startup connect is fatal — the app refuses to come up if the broker
is unreachable, so the operator sees the failure immediately rather
than at first chat send.

Spec §4.3.
"""
from __future__ import annotations

import aiomqtt
import structlog

from observatory.config import Settings
from observatory.sensory.allowlist import ALLOWED_PUBLISH_TOPICS
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    """Same parser as observatory.service — kept local to avoid a back-import."""
    rest = url.split("://", 1)[1]
    host, _, port_s = rest.partition(":")
    return host, int(port_s or "1883")


class SensoryPublisher:
    """The single MQTT writer in observatory. Allowlist-gated.

    All publishes go through `publish()`, which validates the envelope's
    topic against `ALLOWED_PUBLISH_TOPICS` *before* serialising. A wrong
    topic is a programming error — the route always builds an allowlisted
    topic — so we raise `ForbiddenTopicError` (route maps to HTTP 500)
    rather than silently dropping.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: aiomqtt.Client | None = None
        self._host, self._port = _parse_mqtt_url(settings.mqtt_url)

    async def connect(self) -> None:
        """Open the aiomqtt connection. Idempotent: a second call is a no-op."""
        if self._client is not None:
            return
        client = aiomqtt.Client(
            hostname=self._host,
            port=self._port,
            username=self._settings.mqtt_username,
            password=self._settings.mqtt_password,
        )
        await client.__aenter__()
        self._client = client
        log.info("sensory_publisher.connected", host=self._host, port=self._port)

    async def disconnect(self) -> None:
        """Close the aiomqtt connection. Idempotent."""
        if self._client is None:
            return
        try:
            await self._client.__aexit__(None, None, None)
        except Exception as e:  # pragma: no cover — best-effort drain
            log.warning("sensory_publisher.disconnect_error", error=str(e))
        finally:
            self._client = None

    async def publish(self, envelope: Envelope, *, qos: int = 1) -> None:
        """Publish an Envelope to MQTT. Raises if topic not allowlisted or send fails."""
        if envelope.topic not in ALLOWED_PUBLISH_TOPICS:
            raise ForbiddenTopicError(envelope.topic)
        if self._client is None:
            raise RuntimeError(
                "SensoryPublisher.publish called before connect()"
            )
        try:
            await self._client.publish(envelope.topic, envelope.to_json(), qos=qos)
        except aiomqtt.MqttError as e:
            raise PublishFailedError(e) from e
