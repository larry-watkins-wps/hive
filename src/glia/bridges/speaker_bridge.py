"""Speaker bridge — spec §E.8.

Subscribes (conceptually) to ``hive/hardware/speaker`` — since this
task does not wire bridges into a dispatcher yet, ``handle_message``
is exposed so a future dispatcher can call it directly. If
``sounddevice`` is unavailable, messages are logged and dropped.
"""
from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

TOPIC_SPEAKER = "hive/hardware/speaker"
METRICS_TOPIC = "hive/system/metrics/hardware/speaker"

PublishFn = Callable[..., Awaitable[None]]


class SpeakerBridge:
    """MQTT → output audio. Drops messages gracefully when unavailable."""

    name = "speaker_bridge"

    def __init__(self, publish: PublishFn, *, enabled: bool = False) -> None:
        self._publish = publish
        self._enabled = enabled
        self._available = False

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
            sd.check_output_settings()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            await self._publish_unavailable(f"no_output_device: {exc}")
            return

        self._available = True

    async def stop(self) -> None:
        self._available = False

    async def handle_message(self, envelope: Envelope) -> None:
        """Handle a ``hive/hardware/speaker`` envelope.

        v0: if sounddevice is available, this is where audio would be
        played. For now we just log — real playback is follow-up work.
        """
        if not self._available:
            log.debug("speaker_drop_unavailable", topic=envelope.topic)
            return
        log.info("speaker_play", topic=envelope.topic)

    async def _publish_unavailable(self, reason: str) -> None:
        log.warning("speaker_bridge_unavailable", reason=reason)
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "unavailable", "reason": reason},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)
