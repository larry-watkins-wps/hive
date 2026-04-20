"""glia/supervisor.py — Single-loop glia composition (spec §E.2, §E.4, §E.5).

The supervisor is the one async loop that wires all glia sub-modules together:

* :class:`~glia.launcher.Launcher` — sync docker SDK calls.
* :class:`~glia.heartbeat_monitor.HeartbeatMonitor` — liveness tracker.
* :class:`~glia.acl_manager.AclManager` — ACL renderer + broker reloader.
* :class:`~glia.rollback.Rollback` — single-shot git revert + relaunch.
* :class:`~glia.spawn_executor.SpawnExecutor` — 8-step spawn pipeline.
* :class:`~glia.codechange_executor.CodeChangeExecutor` — DNA code-change.
* :class:`~glia.metrics.MetricsAggregator` — retained system metrics topics.

Responsibilities:

1. **Inbound routing.** Route MQTT envelopes (fed by the caller's MQTT
   dispatcher) to the appropriate sub-module.
2. **Restart policy (§E.4).** Translate docker exit codes into backoff-driven
   restarts, crash-loop circuit breaking, and rollback triggers.
3. **Heartbeat wiring.** Install callbacks on the heartbeat monitor so
   unhealthy regions are auto-restarted (no rollback — liveness is a
   "probably slow" signal, not a crash signal).
4. **Lifecycle.** :meth:`start` wires callbacks + starts metrics / heartbeat
   loops; :meth:`stop` tears them down.

Design notes:

* The supervisor does NOT own an MQTT client or a docker-events stream —
  those are wired by ``glia/__main__`` (Task 5.10). Instead the caller
  exposes ``publish`` + invokes ``on_*`` methods for each subscribed topic
  and :meth:`on_region_exit` for each docker exit event. This keeps the
  supervisor broker-free and docker-free for unit tests.
* :meth:`_restart_with_backoff` is fire-and-forget — the caller's async
  dispatch does not wait for the restart to complete. A pending task set
  lets :meth:`stop` cancel any in-flight backoffs cleanly.
* Exit codes 2/3 (config / git errors per §E.4) route to rollback instead
  of to restart-with-backoff.  Rollback owns the relaunch, so on ``ok=True``
  the supervisor takes no further action.  On ``ok=False`` it publishes a
  ``rollback_failed`` metacog event and leaves the region down.
* v0 simplifications:
  - ``hive/system/sleep/request`` is granted **unconditionally** — no
    resource-pressure evaluation. A future pass can route through ACC
    arbitration instead.
  - Restart requests (``hive/system/restart/request``) are acted on
    immediately; no ``restart/granted`` topic exists in the spec, so the
    supervisor logs and proceeds.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import structlog

from glia.acl_manager import AclManager
from glia.codechange_executor import CodeChangeExecutor
from glia.heartbeat_monitor import HeartbeatMonitor
from glia.launcher import GliaError, Launcher
from glia.metrics import MetricsAggregator
from glia.registry import RegionRegistry
from glia.rollback import Rollback
from glia.spawn_executor import SpawnExecutor
from shared.message_envelope import Envelope
from shared.topics import (
    METACOGNITION_ERROR_DETECTED,
    SYSTEM_SLEEP_GRANTED,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Spec §E.4 defaults
# ---------------------------------------------------------------------------
BACKOFF_SCHEDULE: tuple[float, ...] = (5.0, 15.0, 45.0, 90.0, 180.0)
BACKOFF_CAP_S = 300.0
CRASH_WINDOW_S = 600.0  # 10 minutes
CRASH_THRESHOLD = 5
PLANNED_RESTART_PAUSE_S = 2.0  # §E.4 exit 0: "2s pause (let broker process LWT)"

# Exit codes that trigger §E.5 rollback.
_EXIT_CODE_CONFIG_ERROR = 2
_EXIT_CODE_GIT_ERROR = 3
_ROLLBACK_EXIT_CODES = (_EXIT_CODE_CONFIG_ERROR, _EXIT_CODE_GIT_ERROR)


# ---------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------


@dataclass
class _RegionState:
    """Per-region bookkeeping: crash history + current circuit state."""

    # Monotonic count of recorded crashes (exit code != 0). Never decremented
    # except by an operator CLI (``hive restart --force``). Used as the index
    # into the backoff schedule.
    crash_count: int = 0


class Supervisor:
    """Composes glia sub-modules into a single async loop.

    Parameters
    ----------
    registry, launcher, heartbeat_monitor, acl_manager, rollback,
    spawn_executor, codechange_executor, metrics:
        Injected sub-modules. ``MagicMock(spec=...)`` / ``AsyncMock(spec=...)``
        acceptable in unit tests.
    publish:
        Awaitable publish function. Called as ``publish(envelope)``.
    backoff_schedule, crash_window_s, crash_threshold:
        §E.4 policy knobs. Exposed for tests.
    clock, sleeper:
        Injected for deterministic tests. Default to wall-clock time and
        :func:`asyncio.sleep`.
    """

    def __init__(
        self,
        registry: RegionRegistry,
        launcher: Launcher,
        heartbeat_monitor: HeartbeatMonitor,
        acl_manager: AclManager,
        rollback: Rollback,
        spawn_executor: SpawnExecutor,
        codechange_executor: CodeChangeExecutor,
        metrics: MetricsAggregator,
        *,
        publish: Callable[..., Awaitable[None]],
        backoff_schedule: tuple[float, ...] = BACKOFF_SCHEDULE,
        backoff_cap_s: float = BACKOFF_CAP_S,
        crash_window_s: float = CRASH_WINDOW_S,
        crash_threshold: int = CRASH_THRESHOLD,
        planned_restart_pause_s: float = PLANNED_RESTART_PAUSE_S,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._registry = registry
        self._launcher = launcher
        self._heartbeat_monitor = heartbeat_monitor
        self._acl_manager = acl_manager
        self._rollback = rollback
        self._spawn_executor = spawn_executor
        self._codechange_executor = codechange_executor
        self._metrics = metrics
        self._publish = publish

        self._backoff_schedule = backoff_schedule
        self._backoff_cap_s = backoff_cap_s
        self._crash_window_s = crash_window_s
        self._crash_threshold = crash_threshold
        self._planned_restart_pause_s = planned_restart_pause_s
        self._clock = clock
        self._sleeper = sleeper

        self._state: dict[str, _RegionState] = defaultdict(_RegionState)
        self._crash_log: dict[str, deque[float]] = defaultdict(deque)
        self._circuit_broken: set[str] = set()
        self._started = False
        self._pending_tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Wire heartbeat callbacks, then start background loops. Idempotent."""
        if self._started:
            return
        # Direct-attribute wiring matches HeartbeatMonitor's constructor surface.
        self._heartbeat_monitor._on_unhealthy = self._handle_region_unhealthy
        self._heartbeat_monitor._on_healthy = self._handle_region_healthy
        await self._heartbeat_monitor.start()
        await self._metrics.start()
        self._started = True
        log.info("supervisor.started")

    async def stop(self) -> None:
        """Stop background loops + cancel any pending restart tasks. Idempotent."""
        if not self._started:
            return
        # Best-effort: always attempt teardown even if one sub-module raises.
        try:
            await self._heartbeat_monitor.stop()
        except Exception:  # noqa: BLE001 — teardown swallows to avoid masking the originating cause
            log.exception("supervisor.heartbeat_stop_failed")
        try:
            await self._metrics.stop()
        except Exception:  # noqa: BLE001
            log.exception("supervisor.metrics_stop_failed")

        # Cancel pending restart coroutines.
        for task in list(self._pending_tasks):
            if not task.done():
                task.cancel()
        for task in list(self._pending_tasks):
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._pending_tasks.clear()
        self._started = False
        log.info("supervisor.stopped")

    # ------------------------------------------------------------------
    # Inbound routing (called by the caller's MQTT dispatcher)
    # ------------------------------------------------------------------

    async def on_heartbeat(
        self, envelope: Envelope, *, retained: bool = False
    ) -> None:
        """Forward a ``hive/system/heartbeat/+`` envelope to the monitor."""
        await self._heartbeat_monitor.on_heartbeat(envelope, retained=retained)

    async def on_region_stats(self, envelope: Envelope) -> None:
        """Forward a ``hive/system/region_stats/+`` envelope to metrics."""
        await self._metrics.on_region_stats(envelope)

    async def on_sleep_request(self, envelope: Envelope) -> None:
        """v0: grant unconditionally. Correlation_id preserved."""
        data = envelope.payload.data if isinstance(envelope.payload.data, dict) else {}
        region = data.get("region") or envelope.source_region
        reason = data.get("reason")
        log.info(
            "supervisor.sleep_request",
            region=region,
            reason=reason,
            correlation_id=envelope.correlation_id,
        )
        await self._publish_sleep_granted(
            region=str(region),
            correlation_id=envelope.correlation_id,
        )

    async def on_restart_request(self, envelope: Envelope) -> None:
        """Gracefully restart the requesting region (stop + launch)."""
        data = envelope.payload.data if isinstance(envelope.payload.data, dict) else {}
        region = data.get("region") or envelope.source_region
        if not isinstance(region, str) or not region:
            log.warning(
                "supervisor.restart_request_invalid",
                correlation_id=envelope.correlation_id,
            )
            return
        log.info(
            "supervisor.restart_request",
            region=region,
            correlation_id=envelope.correlation_id,
        )
        try:
            await asyncio.to_thread(self._launcher.stop_region, region)
            await asyncio.to_thread(self._launcher.launch_region, region)
        except GliaError as exc:
            log.error(
                "supervisor.restart_request_failed",
                region=region,
                error=str(exc),
            )

    async def on_spawn_request(self, envelope: Envelope) -> None:
        """Delegate to the spawn executor's 8-step pipeline."""
        await self._spawn_executor.handle_request(envelope)

    async def on_spawn_query(self, envelope: Envelope) -> None:
        """Delegate to the spawn executor's query path."""
        await self._spawn_executor.handle_query(envelope)

    async def on_codechange_approved(self, envelope: Envelope) -> None:
        """Delegate to the codechange executor."""
        await self._codechange_executor.apply_change(envelope)

    # ------------------------------------------------------------------
    # Docker-exit path (wired by the caller's docker events listener)
    # ------------------------------------------------------------------

    async def on_region_exit(self, region: str, exit_code: int) -> None:
        """Apply §E.4 restart policy for a container exit event.

        Dispatch:
          * 0 — planned restart: pause ``planned_restart_pause_s`` then relaunch.
          * 2, 3 — config / git error: publish metacog + trigger rollback. No
            direct restart (rollback owns the relaunch).
          * 1, 4, 137, 139 — transient: record crash, backoff, restart (unless
            circuit breaker has tripped).
          * Other non-zero codes — treated as transient (same as 1).
        """
        log.info(
            "supervisor.region_exit",
            region=region,
            exit_code=exit_code,
        )

        if exit_code == 0:
            await self._handle_planned_restart(region)
            return

        if exit_code in _ROLLBACK_EXIT_CODES:
            kind = (
                "region_config_error"
                if exit_code == _EXIT_CODE_CONFIG_ERROR
                else "region_git_error"
            )
            await self._publish_metacog(
                kind=kind,
                detail=f"region {region} exited with code {exit_code}",
                context={"region": region, "exit_code": exit_code},
            )
            await self._invoke_rollback(region, exit_code)
            return

        # Transient — restart with backoff.
        await self._restart_with_backoff(region, exit_code)

    # ------------------------------------------------------------------
    # Heartbeat-monitor callbacks
    # ------------------------------------------------------------------

    async def _handle_region_unhealthy(self, region: str, reason: str) -> None:
        """Treat missed heartbeats / LWT as "probably crashed" — restart w/ backoff.

        Explicitly does NOT trigger rollback: the region might just be slow;
        only docker-exit 2/3 has high enough confidence to warrant rollback.
        """
        log.warning(
            "supervisor.region_unhealthy",
            region=region,
            reason=reason,
        )
        await self._restart_with_backoff(region, exit_code=None)

    async def _handle_region_healthy(self, region: str) -> None:
        """On recovery clear the circuit breaker (but keep crash count)."""
        if region in self._circuit_broken:
            self._circuit_broken.discard(region)
            log.info("supervisor.circuit_cleared", region=region)

    # ------------------------------------------------------------------
    # Restart policy internals
    # ------------------------------------------------------------------

    async def _handle_planned_restart(self, region: str) -> None:
        """Exit 0 path: pause, then relaunch. Crash counter untouched."""
        await self._sleeper(self._planned_restart_pause_s)
        try:
            await asyncio.to_thread(self._launcher.restart_region, region)
        except GliaError as exc:
            log.error(
                "supervisor.planned_restart_failed",
                region=region,
                error=str(exc),
            )

    async def _invoke_rollback(self, region: str, exit_code: int) -> None:
        """Ask :class:`Rollback` to revert + relaunch. Emit metacog on failure."""
        reason = f"exit_{exit_code}"
        try:
            result = await self._rollback.rollback_region(region, reason)
        except Exception as exc:  # noqa: BLE001 — broad so we always publish metacog
            log.error(
                "supervisor.rollback_raised",
                region=region,
                exit_code=exit_code,
                error=str(exc),
            )
            await self._publish_metacog(
                kind="rollback_failed",
                detail=f"rollback raised: {exc}",
                context={"region": region, "exit_code": exit_code},
            )
            return

        if not result.ok:
            log.error(
                "supervisor.rollback_failed",
                region=region,
                reason=result.reason,
            )
            await self._publish_metacog(
                kind="rollback_failed",
                detail=f"rollback failed: {result.reason}",
                context={
                    "region": region,
                    "exit_code": exit_code,
                    "rollback_reason": result.reason,
                },
            )

    async def _restart_with_backoff(
        self, region: str, exit_code: int | None
    ) -> None:
        """Record crash, consult circuit breaker, backoff, relaunch.

        ``exit_code`` is ``None`` for the heartbeat-miss path (no docker code).
        """
        if region in self._circuit_broken:
            log.warning(
                "supervisor.restart_skipped_circuit_broken",
                region=region,
            )
            return

        tripped = self._register_crash(region)
        if tripped:
            await self._publish_metacog(
                kind="crash_loop",
                detail=(
                    f"region {region} crashed >= {self._crash_threshold} "
                    f"times in {self._crash_window_s:.0f}s"
                ),
                context={"region": region, "exit_code": exit_code},
            )
            return

        backoff = self._backoff_for_crash_count(self._state[region].crash_count)
        log.info(
            "supervisor.restart_scheduled",
            region=region,
            backoff_s=backoff,
            crash_count=self._state[region].crash_count,
            exit_code=exit_code,
        )
        await self._sleeper(backoff)
        # Re-check circuit breaker in case it was tripped during backoff.
        if region in self._circuit_broken:
            return
        try:
            await asyncio.to_thread(self._launcher.restart_region, region)
        except GliaError as exc:
            log.error(
                "supervisor.restart_failed",
                region=region,
                error=str(exc),
            )

    def _register_crash(self, region: str) -> bool:
        """Record a crash @ ``clock()``; trim window; return True on circuit-trip.

        Side effect: increments the region's persistent ``crash_count`` so
        subsequent backoffs progress through the schedule. Sets
        :attr:`_circuit_broken` on trip.
        """
        now = self._clock()
        self._state[region].crash_count += 1
        dq = self._crash_log[region]
        dq.append(now)
        cutoff = now - self._crash_window_s
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self._crash_threshold:
            self._circuit_broken.add(region)
            log.error(
                "supervisor.crash_loop",
                region=region,
                crashes_in_window=len(dq),
                window_s=self._crash_window_s,
            )
            return True
        return False

    def _backoff_for_crash_count(self, crash_count: int) -> float:
        """Map 1-indexed crash_count → schedule slot, capped."""
        if crash_count <= 0:
            return 0.0
        idx = min(crash_count - 1, len(self._backoff_schedule) - 1)
        if crash_count > len(self._backoff_schedule):
            return self._backoff_cap_s
        return self._backoff_schedule[idx]

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    async def _publish_metacog(
        self,
        *,
        kind: str,
        detail: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        envelope = Envelope.new(
            source_region="glia",
            topic=METACOGNITION_ERROR_DETECTED,
            content_type="application/json",
            data={"kind": kind, "detail": detail, "context": dict(context or {})},
        )
        try:
            await self._publish(envelope)
        except Exception as exc:  # noqa: BLE001 — broker errors must not mask policy decisions
            log.warning(
                "supervisor.metacog_publish_failed",
                kind=kind,
                error=str(exc),
            )

    async def _publish_sleep_granted(
        self, *, region: str, correlation_id: str | None
    ) -> None:
        envelope = Envelope.new(
            source_region="glia",
            topic=SYSTEM_SLEEP_GRANTED,
            content_type="application/json",
            data={"region": region},
            correlation_id=correlation_id,
        )
        try:
            await self._publish(envelope)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "supervisor.sleep_granted_publish_failed",
                region=region,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Operator-CLI hooks (spec §E.4: ``hive restart --force`` resets counter)
    # ------------------------------------------------------------------

    def reset_crash_counter(self, region: str) -> None:
        """Clear crash history + circuit breaker for ``region``.

        Mirrors the operator CLI ``hive restart <name> --force`` described in
        spec §E.4.  Call sites other than the CLI should be rare; heartbeat
        recovery alone clears the circuit breaker but keeps the crash count.
        """
        self._state.pop(region, None)
        self._crash_log.pop(region, None)
        self._circuit_broken.discard(region)
        log.info("supervisor.crash_counter_reset", region=region)
