"""Camera bridge — spec §E.8.

Publishes raw video frames to ``hive/hardware/camera``. At v0 the
bridge is *disabled by default* and the capture loop is a minimal
stub — the hard work is graceful-degrade (no ``cv2`` installed, no
default camera).
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

TOPIC_CAMERA = "hive/hardware/camera"
METRICS_TOPIC = "hive/system/metrics/hardware/camera"

PublishFn = Callable[..., Awaitable[None]]


class CameraBridge:
    """Input video → MQTT. Gracefully degrades when cv2/hardware absent."""

    name = "camera_bridge"

    def __init__(self, publish: PublishFn, *, enabled: bool = False, device_index: int = 0) -> None:
        self._publish = publish
        self._enabled = enabled
        self._device_index = device_index
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
            import cv2  # type: ignore[import-not-found]  # noqa: PLC0415 (lazy: optional dep)
        except ImportError:
            await self._publish_unavailable("cv2_not_installed")
            return

        try:
            cap = cv2.VideoCapture(self._device_index)  # type: ignore[attr-defined]
            opened = bool(cap.isOpened())
            cap.release()
        except Exception as exc:  # noqa: BLE001
            await self._publish_unavailable(f"videocapture_error: {exc}")
            return

        if not opened:
            await self._publish_unavailable(f"no_camera_at_index_{self._device_index}")
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
        """Stub video loop. v0: idle until cancelled."""
        log.debug("camera_bridge_loop_started")
        try:
            while not self._stopping:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        finally:
            log.debug("camera_bridge_loop_stopped")

    async def _publish_unavailable(self, reason: str) -> None:
        log.warning("camera_bridge_unavailable", reason=reason)
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "unavailable", "reason": reason},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)
