"""In-memory MQTT fake for unit tests.

Mirrors :class:`region_template.mqtt_client.MqttClient`'s async-context-manager
+ publish/subscribe/unsubscribe API so tests can pass a ``FakeMqttClient``
anywhere the real client is expected.

What the fake does:
- ``publish`` builds an :class:`~shared.message_envelope.Envelope` with the
  same auto-enrichment (``source_region``, ``id``, ``timestamp``) the real
  client performs, and records the call in ``published`` for assertions.
- ``subscribe`` registers a handler for a topic filter. Multiple handlers per
  filter are supported.
- ``inject(topic, envelope)`` simulates broker delivery to all handlers whose
  filters match the topic (via :func:`shared.topics.topic_matches`).
- ``unsubscribe`` stops delivery, either for a single handler or for the whole
  filter.

What the fake deliberately does NOT do:
- **Retained-flag persistence.** That is a broker-side concern and is exercised
  against real Mosquitto in ``tests/component/test_mqtt_real_broker.py``.
- **Reconnect loops.** There is no connection to drop.
- **ACL enforcement.** The real broker enforces ACLs; unit tests don't.
- **Queue overflow.** The fake records everything without bounds.
"""
from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from shared.message_envelope import ContentType, Envelope
from shared.topics import topic_matches

Handler = Callable[[Envelope], Awaitable[None]]


class FakeMqttClient:
    """In-memory stand-in for :class:`region_template.mqtt_client.MqttClient`."""

    published: list[tuple[str, Envelope, int, bool]]

    def __init__(self, region_name: str = "test_region") -> None:
        self._region_name = region_name
        self.published = []
        # topic_filter -> list of handlers
        self._subscriptions: dict[str, list[Handler]] = {}
        self._entered = False

    # ------------------------------------------------------------------
    # Async-context-manager API (matches real client)
    # ------------------------------------------------------------------

    async def __aenter__(self) -> FakeMqttClient:
        self._entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._entered = False

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        *,
        topic: str,
        content_type: ContentType,
        data: Any,
        encoding: Literal["utf-8", "base64"] = "utf-8",
        reply_to: str | None = None,
        correlation_id: str | None = None,
        attention_hint: float = 0.5,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Build an enriched envelope and record it."""
        envelope = Envelope.new(
            source_region=self._region_name,
            topic=topic,
            content_type=content_type,
            data=data,
            encoding=encoding,
            reply_to=reply_to,
            correlation_id=correlation_id,
            attention_hint=attention_hint,
        )
        self.published.append((topic, envelope, qos, retain))

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        topic_filter: str,
        handler: Handler,
        qos: int = 1,
    ) -> None:
        """Register a handler for envelopes matching ``topic_filter``."""
        self._subscriptions.setdefault(topic_filter, []).append(handler)

    async def unsubscribe(
        self,
        topic_filter: str,
        handler: Handler | None = None,
    ) -> None:
        """Stop delivery.

        If ``handler`` is ``None``, remove every handler for the filter.
        Unknown filters are no-ops (so callers need not track subscribe state).
        """
        if topic_filter not in self._subscriptions:
            return
        if handler is None:
            del self._subscriptions[topic_filter]
            return
        handlers = self._subscriptions[topic_filter]
        # Remove a single occurrence; silently no-op if absent.
        with contextlib.suppress(ValueError):
            handlers.remove(handler)
        if not handlers:
            del self._subscriptions[topic_filter]

    # ------------------------------------------------------------------
    # Test-only helpers
    # ------------------------------------------------------------------

    async def inject(self, topic: str, envelope: Envelope) -> None:
        """Simulate the broker delivering ``envelope`` on ``topic``.

        Dispatches to every handler whose filter matches. Handler exceptions
        propagate — tests that want to assert on handler errors can ``assert
        raises`` around ``inject``. The real client instead logs and drops.
        """
        for topic_filter, handlers in list(self._subscriptions.items()):
            if topic_matches(topic_filter, topic):
                for handler in list(handlers):
                    await handler(envelope)

    async def run(self) -> None:
        """No-op.

        The real client drains aiomqtt's receive queue in ``run``; the fake
        delivers synchronously via ``inject`` and has nothing to loop over.
        """
        return None
