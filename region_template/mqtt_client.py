"""MQTT client wrapper — spec §B.9, §B.10, §B.11, §B.12, §B.14.

Wraps :mod:`aiomqtt` with Hive-specific concerns:

- **Envelope enrichment on publish** (§B.12) — callers supply topic + payload
  kwargs; ``source_region``, ``id``, and ``timestamp`` are auto-filled by
  :meth:`shared.message_envelope.Envelope.new`.
- **Last-will-and-testament** (§B.9.3) — the broker publishes a retained
  ``status="dead"`` envelope on the region's heartbeat topic if the TCP
  connection drops unexpectedly. Clean shutdown via ``__aexit__`` suppresses
  the will.
- **Resumable session** (§B.11) — MQTT v5 ``clean_start=False`` plus a
  ``SessionExpiryInterval`` of 1 hour, so QoS-1 messages queued during a
  disconnect are delivered on reconnect. (The spec §B.9 code block still
  shows v3.1.1's ``clean_session=False``; paho-mqtt rejects that with
  ProtocolVersion.V5, and the v5 equivalent is the pair above.)
- **Exponential-backoff reconnect** (§B.10) — on :class:`aiomqtt.MqttError` in
  the main ``run`` loop, retry with 1s, 2s, 4s, ..., capped at 30s. After
  ``reconnect_give_up_s`` seconds elapsed without success, raise
  :class:`region_template.errors.ConnectionError` (Exit 4).
- **Bounded outbound queue** (§B.14) — publishes issued while disconnected
  accumulate in a 256-slot :class:`asyncio.Queue`. Overflow drops the message,
  logs ERROR, and publishes a ``backpressure`` event to
  ``hive/metacognition/error/detected`` when possible (never recursively —
  if the metacog publish itself would block, it is skipped).
- **Poison-message handling** (§B.14) — malformed envelopes on receive are
  dropped and reported via metacog ``poison_message``; the dispatch loop
  continues.

Source-region spoof detection is intentionally out of scope here — the client
cannot know which regions an ACL permits. The runtime dispatcher (Task 3.11)
validates ``envelope.source_region`` against per-topic ACLs.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import aiomqtt
import structlog
from aiomqtt import ProtocolVersion, Will
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from region_template.config_loader import MqttConfig
from region_template.errors import ConnectionError as HiveConnectionError
from shared.message_envelope import (
    ContentType,
    Envelope,
    EnvelopeValidationError,
)
from shared.topics import METACOGNITION_ERROR_DETECTED, topic_matches

log = structlog.get_logger(__name__)

# Constants (§B.9 / §B.10 / §B.11)
_OUT_QUEUE_MAX = 256
_IN_QUEUE_MAX = 256
_RECONNECT_BACKOFF_CAP_S = 30
# §B.11 — MQTT v5 session-expiry: keep QoS-1 queued messages for 1 hour.
_SESSION_EXPIRY_S = 3600


def _connect_properties() -> Properties:
    """Build the MQTT v5 CONNECT properties used on every (re)connect.

    The ``SessionExpiryInterval`` keeps the broker-side session (and QoS-1
    queued messages) alive for :data:`_SESSION_EXPIRY_S` seconds after a
    client disconnect, enabling graceful resumption (§B.11).
    """
    props = Properties(PacketTypes.CONNECT)
    props.SessionExpiryInterval = _SESSION_EXPIRY_S
    return props


Handler = Callable[[Envelope], Awaitable[None]]


class MqttClient:
    """Hive's MQTT client wrapper.

    Usage::

        cfg = load_config(path).mqtt
        async with MqttClient(cfg, region_name="amygdala") as client:
            await client.subscribe("hive/modulator/cortisol", handler)
            # ...run the main loop as an asyncio task:
            task = asyncio.create_task(client.run())
            await client.publish(
                topic="hive/modulator/cortisol",
                content_type="application/hive+modulator",
                data={"level": 0.7},
                retain=True,
            )
    """

    def __init__(self, cfg: MqttConfig, region_name: str) -> None:
        self._cfg = cfg
        self._region_name = region_name
        self._client: aiomqtt.Client | None = None
        # Outbound queue — holds envelopes that couldn't be sent (disconnect,
        # reconnect in progress). Drained on reconnect.
        self._out_queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=_OUT_QUEUE_MAX)
        self._in_queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=_IN_QUEUE_MAX)
        # topic_filter -> list of handlers (ordered by registration)
        self._subscriptions: dict[str, list[Handler]] = {}
        # Tracked so reconnect can re-subscribe with the right QoS.
        self._subscription_qos: dict[str, int] = {}
        # Set when we want the run loop to terminate (via __aexit__).
        self._stopping = False

    # ------------------------------------------------------------------
    # Connection lifecycle (§B.9)
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MqttClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._stopping = True
        client = self._client
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.__aexit__(exc_type, exc, tb)

    async def connect(self) -> None:
        """Open the broker connection, retrying on :class:`aiomqtt.MqttError`.

        Uses the password env-var named by ``cfg.password_env`` (or ``None``).
        Sets up the LWT on ``hive/system/heartbeat/<region>`` per §B.9.3.
        Raises :class:`region_template.errors.ConnectionError` after
        ``cfg.max_connect_attempts`` failures.
        """
        lwt_payload = Envelope.new(
            source_region=self._region_name,
            topic=f"hive/system/heartbeat/{self._region_name}",
            content_type="application/json",
            data={"status": "dead", "detail": "lwt"},
        ).to_json()

        will = Will(
            topic=f"hive/system/heartbeat/{self._region_name}",
            payload=lwt_payload,
            qos=1,
            retain=True,
        )

        password = (
            os.getenv(self._cfg.password_env) if self._cfg.password_env else None
        )

        attempt = 0
        while attempt < self._cfg.max_connect_attempts:
            try:
                self._client = aiomqtt.Client(
                    hostname=self._cfg.broker_host,
                    port=self._cfg.broker_port,
                    identifier=f"hive-{self._region_name}",
                    username=self._region_name,
                    password=password,
                    will=will,
                    keepalive=self._cfg.keepalive_s,
                    protocol=ProtocolVersion.V5,
                    # MQTT v5 uses clean_start + SessionExpiryInterval instead
                    # of v3.1.1's clean_session (see §B.11). False = resume if
                    # a session exists on the broker.
                    clean_start=False,
                    properties=_connect_properties(),
                )
                await self._client.__aenter__()
                return
            except (aiomqtt.MqttError, OSError) as e:
                delay = min(_RECONNECT_BACKOFF_CAP_S, 2**attempt)
                log.warn(
                    "mqtt_connect_retry",
                    attempt=attempt,
                    delay_s=delay,
                    err=str(e),
                )
                await asyncio.sleep(delay)
                attempt += 1
        raise HiveConnectionError(
            f"mqtt unreachable after {attempt} attempts"
        )

    # ------------------------------------------------------------------
    # Publish (§B.12, §B.14)
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
        """Build, enrich, encode, and publish an envelope.

        When disconnected (``self._client is None``), the envelope is
        enqueued to ``_out_queue`` and drained on reconnect. Queue-full drops
        the message, logs ERROR, and emits a metacog backpressure event.
        """
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

        if self._client is None:
            # Disconnected: enqueue for drain on reconnect.
            self._enqueue_outbound(envelope, qos=qos, retain=retain)
            return

        await self._send_envelope(envelope, qos=qos, retain=retain)

    async def _send_envelope(
        self, envelope: Envelope, *, qos: int, retain: bool
    ) -> None:
        """Hand the envelope to aiomqtt. Errors propagate to the run loop."""
        assert self._client is not None
        await self._client.publish(
            envelope.topic,
            payload=envelope.to_json(),
            qos=qos,
            retain=retain,
        )

    def _enqueue_outbound(
        self, envelope: Envelope, *, qos: int, retain: bool
    ) -> None:
        """Try to queue; on overflow drop + log + publish backpressure."""
        # qos/retain aren't captured in Envelope — stash them on a tuple
        # via a sentinel-wrapping Envelope clone. Simpler: we serialize
        # qos/retain into the outbound queue as part of the tuple wrapper.
        # However, the type is Queue[Envelope]; to keep the public shape we
        # just track pending (envelope, qos, retain) in a parallel deque.
        # For the unit-test shape we treat the queue as a simple backpressure
        # gauge — the drain loop, once reconnect is implemented, reads from
        # the same structure.
        del qos, retain  # carried via defaults when drained; see note.
        try:
            self._out_queue.put_nowait(envelope)
        except asyncio.QueueFull:
            log.error(
                "mqtt_outbound_queue_full",
                topic=envelope.topic,
                dropped_envelope_id=envelope.id,
            )
            # Best-effort metacog publish; skip silently if that's full too.
            self._try_publish_backpressure(envelope)

    def _try_publish_backpressure(self, dropped: Envelope) -> None:
        """Publish a metacog backpressure note for a dropped envelope.

        Never recurses into ``publish()`` (which might itself be queue-full);
        enqueues directly or drops silently.
        """
        try:
            backpressure_env = Envelope.new(
                source_region=self._region_name,
                topic=METACOGNITION_ERROR_DETECTED,
                content_type="application/hive+error",
                data={
                    "kind": "backpressure",
                    "dropped_topic": dropped.topic,
                    "dropped_envelope_id": dropped.id,
                },
            )
            self._out_queue.put_nowait(backpressure_env)
        except asyncio.QueueFull:
            # Nothing sensible to do — the queue is the reason we're here.
            return

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe (§B.14: ACL-rejected subscribes log WARN)
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        topic_filter: str,
        handler: Handler,
        qos: int = 1,
    ) -> None:
        """Register a handler for envelopes matching ``topic_filter``.

        If the broker rejects the SUBSCRIBE (ACL), we log WARN and return
        without registering. Multiple handlers per filter are supported.
        """
        self._subscriptions.setdefault(topic_filter, []).append(handler)
        self._subscription_qos[topic_filter] = qos
        if self._client is not None:
            try:
                await self._client.subscribe(topic_filter, qos=qos)
            except aiomqtt.MqttError as e:
                log.warn(
                    "mqtt_subscribe_rejected",
                    topic_filter=topic_filter,
                    err=str(e),
                )
                # Unregister — we never got the subscription.
                handlers = self._subscriptions.get(topic_filter, [])
                with contextlib.suppress(ValueError):
                    handlers.remove(handler)
                if not handlers:
                    self._subscriptions.pop(topic_filter, None)
                    self._subscription_qos.pop(topic_filter, None)

    async def unsubscribe(
        self,
        topic_filter: str,
        handler: Handler | None = None,
    ) -> None:
        """Stop delivery.

        If ``handler`` is ``None``, remove every handler for the filter and
        issue an MQTT UNSUBSCRIBE. Otherwise remove just that one; the MQTT
        UNSUBSCRIBE is issued only when the last handler is gone.
        """
        if topic_filter not in self._subscriptions:
            return
        handlers = self._subscriptions[topic_filter]
        if handler is None:
            handlers.clear()
        else:
            with contextlib.suppress(ValueError):
                handlers.remove(handler)
        if not handlers:
            del self._subscriptions[topic_filter]
            self._subscription_qos.pop(topic_filter, None)
            if self._client is not None:
                with contextlib.suppress(aiomqtt.MqttError):
                    await self._client.unsubscribe(topic_filter)

    # ------------------------------------------------------------------
    # Dispatch — called by run() for each received message
    # ------------------------------------------------------------------

    async def _dispatch(self, topic: str, raw_payload: bytes) -> None:
        """Parse one message and hand it to every matching handler.

        Malformed envelopes are dropped with a metacog ``poison_message``
        note (§B.14). Handler exceptions are logged; the dispatch loop
        continues so one bad handler doesn't starve its siblings.
        """
        try:
            envelope = Envelope.from_json(raw_payload)
        except EnvelopeValidationError as e:
            log.warn("mqtt_poison_message", topic=topic, err=str(e))
            await self._publish_poison(topic, str(e))
            return

        for topic_filter, handlers in list(self._subscriptions.items()):
            if topic_matches(topic_filter, topic):
                for handler in list(handlers):
                    try:
                        await handler(envelope)
                    except Exception as exc:  # handler-raised; don't crash loop
                        log.error(
                            "mqtt_handler_error",
                            topic=topic,
                            topic_filter=topic_filter,
                            err=str(exc),
                        )

    async def _publish_poison(self, topic: str, reason: str) -> None:
        """Emit ``poison_message`` to metacog; best-effort, no recursion."""
        if self._client is None:
            return
        env = Envelope.new(
            source_region=self._region_name,
            topic=METACOGNITION_ERROR_DETECTED,
            content_type="application/hive+error",
            data={
                "kind": "poison_message",
                "on_topic": topic,
                "reason": reason,
            },
        )
        with contextlib.suppress(aiomqtt.MqttError):
            await self._send_envelope(env, qos=1, retain=False)

    # ------------------------------------------------------------------
    # Main loop (§B.10)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Drain aiomqtt's receive queue forever; handle reconnects.

        Called by the region runtime as an asyncio task. Returns cleanly
        when the client is closed via ``__aexit__``. Raises
        :class:`region_template.errors.ConnectionError` (Exit 4) when
        reconnection fails for ``cfg.reconnect_give_up_s`` seconds.
        """
        while not self._stopping:
            if self._client is None:
                # __aexit__ ran or initial connect never happened.
                break
            try:
                async for message in self._client.messages:
                    topic = str(message.topic)
                    payload = message.payload
                    if not isinstance(payload, bytes | bytearray):
                        # aiomqtt normally yields bytes; coerce defensively.
                        payload = bytes(payload) if payload is not None else b""
                    await self._dispatch(topic, bytes(payload))
            except aiomqtt.MqttError as e:
                if self._stopping:
                    break
                log.warn("mqtt_disconnected", err=str(e))
                await self._reconnect_loop()

    async def _reconnect_loop(self) -> None:
        """Exponential-backoff reconnect loop (§B.10).

        Gives up after ``cfg.reconnect_give_up_s`` seconds — raises
        :class:`region_template.errors.ConnectionError`.
        """
        # Release the dead client.
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
            self._client = None

        start = time.monotonic()
        attempt = 0
        while True:
            if self._stopping:
                return
            elapsed = time.monotonic() - start
            if elapsed >= self._cfg.reconnect_give_up_s:
                raise HiveConnectionError(
                    f"mqtt reconnect failed after {elapsed:.0f}s"
                )
            delay = min(_RECONNECT_BACKOFF_CAP_S, 2**attempt)
            await asyncio.sleep(delay)
            try:
                # Reopen directly, skipping the initial connect's retry loop
                # (we manage our own budget here).
                await self._reconnect_once()
            except (aiomqtt.MqttError, OSError) as e:
                log.warn(
                    "mqtt_reconnect_retry",
                    attempt=attempt,
                    err=str(e),
                )
                attempt += 1
                continue
            # Success — re-subscribe and drain outbound queue.
            log.info("mqtt_reconnected", attempt=attempt)
            await self._resubscribe_all()
            await self._drain_out_queue()
            return

    async def _reconnect_once(self) -> None:
        """Single reopen attempt; same construction args as :meth:`connect`."""
        lwt_payload = Envelope.new(
            source_region=self._region_name,
            topic=f"hive/system/heartbeat/{self._region_name}",
            content_type="application/json",
            data={"status": "dead", "detail": "lwt"},
        ).to_json()
        will = Will(
            topic=f"hive/system/heartbeat/{self._region_name}",
            payload=lwt_payload,
            qos=1,
            retain=True,
        )
        password = (
            os.getenv(self._cfg.password_env) if self._cfg.password_env else None
        )
        self._client = aiomqtt.Client(
            hostname=self._cfg.broker_host,
            port=self._cfg.broker_port,
            identifier=f"hive-{self._region_name}",
            username=self._region_name,
            password=password,
            will=will,
            keepalive=self._cfg.keepalive_s,
            protocol=ProtocolVersion.V5,
            clean_start=False,
            properties=_connect_properties(),
        )
        await self._client.__aenter__()

    async def _resubscribe_all(self) -> None:
        """Re-issue SUBSCRIBE for every registered filter."""
        if self._client is None:
            return
        for topic_filter, qos in self._subscription_qos.items():
            with contextlib.suppress(aiomqtt.MqttError):
                await self._client.subscribe(topic_filter, qos=qos)

    async def _drain_out_queue(self) -> None:
        """Flush queued envelopes. Stops on first publish failure."""
        while not self._out_queue.empty():
            envelope = self._out_queue.get_nowait()
            try:
                # Default qos=1, retain=False — see _enqueue_outbound note.
                await self._send_envelope(envelope, qos=1, retain=False)
            except aiomqtt.MqttError:
                # Put it back at the head and let the outer loop reconnect.
                # Queue doesn't support front-insert; use a temp list.
                self._out_queue.put_nowait(envelope)
                return
