"""Input text bridge — spec §E.8.

TCP server on localhost:7777. Each newline-delimited line received
publishes a ``text/plain``-typed envelope to ``hive/sensory/input/text``.
This is the only hardware-ish bridge enabled by default at v0 — it has
no optional dependencies and is required for the CLI onboarding flow.
"""
from __future__ import annotations

import asyncio
import contextlib
from asyncio.base_events import Server
from collections.abc import Awaitable, Callable

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

TOPIC_INPUT_TEXT = "hive/sensory/input/text"
METRICS_TOPIC = "hive/system/metrics/hardware/input_text"

PublishFn = Callable[..., Awaitable[None]]


class InputTextBridge:
    """Accepts text over TCP and republishes as MQTT envelopes."""

    name = "input_text_bridge"

    def __init__(
        self,
        publish: PublishFn,
        *,
        host: str = "127.0.0.1",
        port: int = 7777,
    ) -> None:
        self._publish = publish
        self._host = host
        self._port = port
        self._server: Server | None = None

    @property
    def server(self) -> Server | None:
        """Bound server (for tests to read the ephemeral port)."""
        return self._server

    async def start(self) -> None:
        try:
            self._server = await asyncio.start_server(
                self._handle_client, host=self._host, port=self._port
            )
        except OSError as exc:
            log.warning(
                "input_text_bind_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            await self._publish_unavailable(reason=f"bind_failed: {exc}")
            self._server = None

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue
                envelope = Envelope.new(
                    source_region="glia",
                    topic=TOPIC_INPUT_TEXT,
                    content_type="text/plain",
                    data={"text": text},
                )
                try:
                    await self._publish(envelope, qos=1)
                except Exception:  # noqa: BLE001
                    log.warning("input_text_publish_failed", text_len=len(text))
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _publish_unavailable(self, reason: str) -> None:
        log.warning("input_text_bridge_unavailable", reason=reason)
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "unavailable", "reason": reason},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)
