"""Heartbeat emitter for the Hive region runtime — spec §A.5.

Each region emits a heartbeat every ``interval_s`` (default 5s) to
``hive/system/heartbeat/<region>``. Glia subscribes with QoS 1 to
``hive/system/heartbeat/+`` and maintains its own liveness map in memory.

The "dead" status is NOT emitted by this module; the broker publishes a
``dead`` LWT envelope (§B.9.3) on client disconnect.

The heartbeat is decoupled from the MQTT layer: the caller supplies a
``publish`` async callable and a ``state_provider`` callable that returns
the current dynamic state. This keeps the module testable without a full
runtime and lets §A.8's sleep-cycle slowdown swap cadence at any moment
via :meth:`Heartbeat.set_interval`.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from region_template.types import LifecyclePhase
from shared.message_envelope import Envelope
from shared.topics import SYSTEM_HEARTBEAT, fill

HeartbeatStatus = Literal[
    "boot",
    "wake",
    "sleep",
    "sleep_restart",
    "shutdown",
]


@dataclass(frozen=True)
class HeartbeatState:
    """Dynamic fields supplied to each heartbeat tick by the runtime.

    ``status`` excludes ``"dead"`` — that value is reserved for the broker
    LWT per spec §A.5 / §B.9.3.
    """

    status: HeartbeatStatus
    phase: LifecyclePhase
    handler_count: int
    queue_depth_messages: int
    llm_tokens_used_lifetime: int
    stm_bytes: int
    last_error_ts: str | None


def _now_iso_utc_ms() -> str:
    """ISO-8601 UTC with millisecond precision and ``Z`` suffix.

    Matches :class:`shared.message_envelope.Envelope`'s internal
    ``timestamp`` default (see message_envelope.py lines 53-58).
    """
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class Heartbeat:
    """Periodic heartbeat publisher for a single region.

    The tick loop calls ``state_provider()`` then ``publish(envelope)`` on
    each tick. ``start`` and ``stop`` are idempotent; ``set_interval``
    takes effect on the next tick boundary (or immediately if the loop
    was sleeping).
    """

    def __init__(
        self,
        region: str,
        interval_s: float,
        publish: Callable[[Envelope], Awaitable[None]],
        state_provider: Callable[[], HeartbeatState],
        build_sha: str,
    ) -> None:
        self._region = region
        self._interval_s = interval_s
        self._publish = publish
        self._state_provider = state_provider
        self._build_sha = build_sha

        self._topic = fill(SYSTEM_HEARTBEAT, region=region)
        self._boot_monotonic = time.monotonic()

        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._wakeup_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the tick loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._wakeup_event.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"heartbeat-{self._region}"
        )

    async def stop(self) -> None:
        """Stop the tick loop and await cancellation. Idempotent."""
        task = self._task
        if task is None:
            return
        self._stopping = True
        self._wakeup_event.set()  # wake the loop out of its wait
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None

    def set_interval(self, interval_s: float) -> None:
        """Update cadence. Effective on the next tick.

        Signals the sleeping loop so a shortened interval is honoured
        immediately rather than waiting out the previous ``interval_s``.
        """
        self._interval_s = interval_s
        self._wakeup_event.set()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while not self._stopping:
            await self._emit_one()
            if self._stopping:
                break
            try:
                await asyncio.wait_for(
                    self._wakeup_event.wait(), timeout=self._interval_s
                )
            except TimeoutError:
                pass  # normal interval elapsed
            finally:
                self._wakeup_event.clear()

    async def _emit_one(self) -> None:
        state = self._state_provider()
        uptime_s = int(time.monotonic() - self._boot_monotonic)

        # Build payload in the spec §A.5 field order (dict preserves insertion order).
        data = {
            "region": self._region,
            "status": state.status,
            "phase": str(state.phase),
            "ts": _now_iso_utc_ms(),
            "uptime_s": uptime_s,
            "handler_count": state.handler_count,
            "queue_depth_messages": state.queue_depth_messages,
            "llm_tokens_used_lifetime": state.llm_tokens_used_lifetime,
            "stm_bytes": state.stm_bytes,
            "last_error_ts": state.last_error_ts,
            "build_sha": self._build_sha,
        }

        envelope = Envelope.new(
            source_region=self._region,
            topic=self._topic,
            content_type="application/json",
            data=data,
        )
        await self._publish(envelope)
