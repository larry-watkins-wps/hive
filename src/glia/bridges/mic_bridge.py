"""Mic bridge — spec §E.8.

Publishes raw audio frames from the host default input device to
``hive/hardware/mic``. At v0 the bridge is *disabled by default* and
the streaming loop is a minimal stub: the hard work is the graceful-
degrade path (no ``sounddevice`` installed, no input device available)
so glia can start cleanly on headless CI boxes.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

TOPIC_MIC = "hive/hardware/mic"
METRICS_TOPIC = "hive/system/metrics/hardware/mic"

PublishFn = Callable[..., Awaitable[None]]


class MicBridge:
    """Input audio → MQTT. Gracefully degrades when deps/hardware absent."""

    name = "mic_bridge"

    def __init__(self, publish: PublishFn, *, enabled: bool = False) -> None:
        self._publish = publish
        self._enabled = enabled
        self._available = False
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def available(self) -> bool:
        return self._available

    async def start(self) -> None:
        if not self._enabled:
            await self._publish_unavailable("disabled_by_config")
            return

        try:
            import sounddevice as sd  # type: ignore[import-not-found]  # noqa: F401,PLC0415
        except ImportError:
            await self._publish_unavailable("sounddevice_not_installed")
            return

        try:
            sd.check_input_settings()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — PortAudio raises various types
            await self._publish_unavailable(f"no_input_device: {exc}")
            return

        self._available = True
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name=self.name)

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Stub audio loop. v0: just log and idle until cancelled."""
        log.debug("mic_bridge_loop_started")
        try:
            while not self._stopping:
                # v0 stub: real sounddevice.InputStream streaming is a
                # follow-up. For now the bridge "runs" but emits nothing.
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        finally:
            log.debug("mic_bridge_loop_stopped")

    async def _publish_unavailable(self, reason: str) -> None:
        log.warning("mic_bridge_unavailable", reason=reason)
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "unavailable", "reason": reason},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)
