"""Motor bridge — spec §E.8.

Stubbed at v0 (no real actuator). Subscribes (conceptually) to
``hive/hardware/motor``; ``handle_message`` just logs the intended
action. A future dispatcher will route messages here.
"""
from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

TOPIC_MOTOR = "hive/hardware/motor"
METRICS_TOPIC = "hive/system/metrics/hardware/motor"

PublishFn = Callable[..., Awaitable[None]]


class MotorBridge:
    """MQTT → motor. v0 stub: logs received actions, no actuator."""

    name = "motor_bridge"

    def __init__(self, publish: PublishFn, *, enabled: bool = False) -> None:
        self._publish = publish
        self._enabled = enabled

    async def start(self) -> None:
        if not self._enabled:
            await self._publish_unavailable("disabled_by_config")
            return
        # v0: even when "enabled", we have no actuator — publish a
        # stub-available metric so operators can see the bridge is
        # reachable but non-functional.
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "stub", "reason": "no_actuator_at_v0"},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)

    async def stop(self) -> None:
        return None

    async def handle_message(self, envelope: Envelope) -> None:
        """Log a would-be motor action."""
        log.info(
            "motor_action",
            topic=envelope.topic,
            data=envelope.payload.data,
        )

    async def _publish_unavailable(self, reason: str) -> None:
        envelope = Envelope.new(
            source_region="glia",
            topic=METRICS_TOPIC,
            content_type="application/json",
            data={"status": "unavailable", "reason": reason},
        )
        with contextlib.suppress(Exception):
            await self._publish(envelope, qos=1, retain=True)
