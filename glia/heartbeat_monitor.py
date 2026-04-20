"""glia/heartbeat_monitor.py — Passive region liveness tracker (spec §E.3).

The monitor maintains an in-memory ``RegionLiveness`` map keyed by region name.
Callers feed heartbeat envelopes via :meth:`HeartbeatMonitor.on_heartbeat`;
the supervisor owns the MQTT subscription and wires the callback. A
background sweep loop checks for stale records and fires ``on_unhealthy``
when a region crosses the miss threshold. LWT envelopes (retained, with
``status="dead"``) fire ``on_unhealthy`` immediately. A recovering region
(heartbeat after being marked dead) fires ``on_healthy``.

Design notes:

- ``last_heartbeat_ts`` uses an injectable monotonic clock (default
  ``time.monotonic``) — NOT wall clock. Tests pass a mutable clock to
  deterministically advance time.
- The dead flag is a one-shot latch: ``on_unhealthy`` fires exactly once
  per dead→alive→dead cycle. Recovery clears it; the next miss-threshold
  crossing re-arms it.
- The sweep loop is cancellation-safe: :meth:`stop` cancels the task and
  awaits it, tolerating ``CancelledError``.

See spec §E.3 for the authoritative rule set.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Defaults (spec §E.3)
# ---------------------------------------------------------------------------
DEFAULT_INTERVAL_S = 5.0
DEFAULT_MISS_THRESHOLD_S = 30.0
DEFAULT_MAX_MISSES = 3


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class RegionLiveness:
    """Per-region liveness snapshot. Mutable; updated on each heartbeat."""

    region: str
    last_heartbeat_ts: float  # monotonic() at receipt, not the payload ts
    last_status: str
    consecutive_misses: int = 0
    queue_depth: int = 0
    uptime_s: int = 0
    build_sha: str | None = None
    dead: bool = False  # True after LWT received or miss-threshold exceeded


UnhealthyCallback = Callable[[str, str], Awaitable[None]]  # (region, reason)
HealthyCallback = Callable[[str], Awaitable[None]]         # (region,)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class HeartbeatMonitor:
    """Passive liveness tracker with a sweep loop.

    Construction does not start the sweep loop — use :meth:`start` /
    :meth:`stop`. Callers feed envelopes via :meth:`on_heartbeat`.
    """

    def __init__(
        self,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        miss_threshold_s: float = DEFAULT_MISS_THRESHOLD_S,
        max_misses: int = DEFAULT_MAX_MISSES,
        on_unhealthy: UnhealthyCallback | None = None,
        on_healthy: HealthyCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval_s = interval_s
        self._miss_threshold_s = miss_threshold_s
        self._max_misses = max_misses
        self._on_unhealthy = on_unhealthy
        self._on_healthy = on_healthy
        self._clock = clock
        self._liveness: dict[str, RegionLiveness] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def on_heartbeat(self, envelope: Envelope, *, retained: bool = False) -> None:
        """Process one heartbeat envelope.

        - ``status="dead"`` + ``retained=True`` → LWT. Mark dead, fire
          :attr:`on_unhealthy` with reason ``"lwt"``.
        - Any other payload with a valid ``region`` field → normal heartbeat.
          Reset ``consecutive_misses`` and ``dead``; update fields. Fire
          :attr:`on_healthy` if the region was previously dead.
        - Malformed payloads (missing ``region``, non-dict data) are logged
          and skipped; this method never raises.
        """
        data = envelope.payload.data
        if not isinstance(data, dict):
            log.warning(
                "heartbeat_monitor.invalid_payload",
                reason="data_not_dict",
                topic=envelope.topic,
            )
            return

        region = data.get("region")
        if not isinstance(region, str) or not region:
            log.warning(
                "heartbeat_monitor.invalid_payload",
                reason="missing_region",
                topic=envelope.topic,
            )
            return

        status = data.get("status", "")
        if not isinstance(status, str):
            status = str(status)

        # --- LWT branch: status="dead" AND retained -----------------------
        if status == "dead" and retained:
            existing = self._liveness.get(region)
            now = self._clock()
            if existing is None:
                existing = RegionLiveness(
                    region=region,
                    last_heartbeat_ts=now,
                    last_status=status,
                )
                self._liveness[region] = existing
            else:
                existing.last_heartbeat_ts = now
                existing.last_status = status

            already_dead = existing.dead
            existing.dead = True
            if not already_dead:
                log.warning(
                    "heartbeat_monitor.region_dead",
                    region=region,
                    reason="lwt",
                )
                await self._fire_unhealthy(region, "lwt")
            return

        # --- Normal heartbeat path ---------------------------------------
        now = self._clock()
        queue_depth = _coerce_int(data.get("queue_depth_messages", 0))
        uptime_s = _coerce_int(data.get("uptime_s", 0))
        build_sha = data.get("build_sha")
        if build_sha is not None and not isinstance(build_sha, str):
            build_sha = str(build_sha)

        existing = self._liveness.get(region)
        was_dead = existing is not None and existing.dead

        if existing is None:
            existing = RegionLiveness(
                region=region,
                last_heartbeat_ts=now,
                last_status=status,
                consecutive_misses=0,
                queue_depth=queue_depth,
                uptime_s=uptime_s,
                build_sha=build_sha,
                dead=False,
            )
            self._liveness[region] = existing
        else:
            existing.last_heartbeat_ts = now
            existing.last_status = status
            existing.consecutive_misses = 0
            existing.queue_depth = queue_depth
            existing.uptime_s = uptime_s
            existing.build_sha = build_sha
            existing.dead = False

        if was_dead:
            log.info("heartbeat_monitor.region_recovered", region=region)
            await self._fire_healthy(region)

    # ------------------------------------------------------------------
    # Sweep lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the sweep loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(
            self._sweep_loop(), name="heartbeat-monitor-sweep"
        )

    async def stop(self) -> None:
        """Stop the sweep loop. Idempotent and cancellation-safe."""
        self._stopping = True
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._task = None

    # ------------------------------------------------------------------
    # Read-only introspection
    # ------------------------------------------------------------------

    def liveness(self, region: str) -> RegionLiveness | None:
        """Return the live liveness record, or ``None`` if unknown.

        NOTE: returns the same object held in the map, NOT a deep copy.
        Callers must not mutate. Use :meth:`all_liveness` for a shallow
        copy of the map itself.
        """
        return self._liveness.get(region)

    def all_liveness(self) -> dict[str, RegionLiveness]:
        """Shallow copy of the liveness map."""
        return dict(self._liveness)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _sweep_loop(self) -> None:
        try:
            while not self._stopping:
                await self._sweep_once()
                try:
                    await asyncio.sleep(self._interval_s)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass

    async def _sweep_once(self) -> None:
        """One sweep pass: increment miss counters; fire callbacks."""
        now = self._clock()
        for region, rec in list(self._liveness.items()):
            if rec.dead:
                # Already marked dead — don't re-increment or re-fire.
                continue
            gap = now - rec.last_heartbeat_ts
            if gap > self._miss_threshold_s:
                rec.consecutive_misses += 1
                if rec.consecutive_misses > self._max_misses:
                    rec.dead = True
                    log.warning(
                        "heartbeat_monitor.region_dead",
                        region=region,
                        reason="miss_threshold",
                        consecutive_misses=rec.consecutive_misses,
                        gap_s=gap,
                    )
                    await self._fire_unhealthy(region, "miss_threshold")

    async def _fire_unhealthy(self, region: str, reason: str) -> None:
        cb = self._on_unhealthy
        if cb is None:
            return
        try:
            await cb(region, reason)
        except Exception:
            log.exception(
                "heartbeat_monitor.on_unhealthy_failed",
                region=region,
                reason=reason,
            )

    async def _fire_healthy(self, region: str) -> None:
        cb = self._on_healthy
        if cb is None:
            return
        try:
            await cb(region)
        except Exception:
            log.exception("heartbeat_monitor.on_healthy_failed", region=region)


def _coerce_int(v: Any) -> int:
    if isinstance(v, bool):  # bool is int subclass — reject explicitly
        return 0
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
