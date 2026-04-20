"""RegionRuntime — composes every other module into the event loop a region
process runs. Spec §A.3, §A.4.

Public API (spec §A.3.1):
    ``RegionRuntime(config_path)``       — production entry; loads config.
    ``RegionRuntime.from_config(...)``   — test-only entry; inject config+fakes.
    ``await runtime.bootstrap()``         — one-time init (§A.4.2 10 steps).
    ``await runtime.run()``               — event loop; returns only on shutdown.
    ``await runtime.shutdown(reason)``    — graceful teardown; idempotent.

Internal hooks (spec §A.3.1):
    ``_enter_wake`` / ``_enter_sleep`` / ``_enter_shutdown``
    ``_on_message`` / ``_on_heartbeat_tick`` / ``_on_sleep_request_accepted``

Test-only helper:
    ``force_sleep(reason)`` — simulates an external ``hive/system/sleep/force``
    trigger, short-circuiting the monitor loop. NOT part of the public spec;
    used by unit tests to exercise the sleep transition directly.

Protocol obligations (for :class:`~region_template.self_modify.SelfModifyTools`
and :class:`~region_template.sleep.SleepCoordinator`):
    ``.phase / .region_name / .region_root / .memory / .llm / .tools / .git``
    ``async publish_restart_request(reason)``
    ``async publish_spawn_request(proposal, correlation_id) -> Future[SpawnResult]``
    ``async shutdown(reason)``
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from ruamel.yaml import YAML

from region_template.config_loader import RegionConfig, load_config
from region_template.git_tools import GitTools
from region_template.handlers_loader import (
    HandlerModule,
    discover,
    match_handlers_for_topic,
)
from region_template.heartbeat import Heartbeat, HeartbeatState
from region_template.llm_adapter import LlmAdapter
from region_template.logging_setup import configure_logging
from region_template.memory import MemoryStore
from region_template.mqtt_client import MqttClient
from region_template.self_modify import (
    SelfModifyTools,
    SpawnProposal,
    SpawnResult,
)
from region_template.sleep import SleepCoordinator, SleepResult, SleepTrigger
from region_template.token_ledger import TokenLedger
from region_template.types import (
    CapabilityProfile,
    HandlerContext,
    LifecyclePhase,
)
from shared.message_envelope import Envelope
from shared.topics import (
    BROADCAST_SHUTDOWN,
    METACOGNITION_ERROR_DETECTED,
    MODULATOR_CORTISOL,
    SYSTEM_HEARTBEAT,
    SYSTEM_RESTART_REQUEST,
    SYSTEM_SLEEP_FORCE,
    SYSTEM_SLEEP_GRANTED,
    SYSTEM_SLEEP_REQUEST,
    SYSTEM_SPAWN_COMPLETE,
    SYSTEM_SPAWN_FAILED,
    SYSTEM_SPAWN_REQUEST,
    fill,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# §A.4.4 step 2 — wait 60 s for sleep/granted.
_SLEEP_GRANT_TIMEOUT_S: float = 60.0

# §D.5.5 — dry-import verification gate timeout.
_PRE_RESTART_VERIFY_TIMEOUT_S: float = 30.0

# Backstop poll for _sleep_monitor.
_SLEEP_MONITOR_TICK_S: float = 0.1

# How often the sleep monitor re-measures STM size. Decoupled from the
# monitor tick so STM pressure is observed at most once per second regardless
# of how aggressively the rest of the monitor polls.
_STM_PRESSURE_CHECK_INTERVAL_S: float = 1.0


# ---------------------------------------------------------------------------
# RegionRuntime
# ---------------------------------------------------------------------------


class RegionRuntime:
    """Integrator — one instance per region process."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        config_path: Path,
    ) -> None:
        """Production entry: load config from disk and set initial state.

        Tests can pass a pre-built :class:`RegionConfig` and inject fakes via
        :meth:`from_config`.
        """
        path = Path(config_path)
        cfg = load_config(path)
        self._init_state(
            config=cfg,
            config_path=path,
            region_root=path.parent,
            mqtt_client=None,
            llm_adapter=None,
            memory_store=None,
        )

    @classmethod
    def from_config(
        cls,
        *,
        config: RegionConfig,
        region_root: Path,
        mqtt_client: Any | None = None,
        llm_adapter: Any | None = None,
        memory_store: Any | None = None,
    ) -> RegionRuntime:
        """Test-only factory: bypass YAML load, inject pre-built modules.

        The config_path attribute is set to ``region_root/config.yaml`` for
        completeness, but the file need not exist.
        """
        runtime = cls.__new__(cls)
        runtime._init_state(
            config=config,
            config_path=Path(region_root) / "config.yaml",
            region_root=Path(region_root),
            mqtt_client=mqtt_client,
            llm_adapter=llm_adapter,
            memory_store=memory_store,
        )
        return runtime

    def _init_state(
        self,
        *,
        config: RegionConfig,
        config_path: Path,
        region_root: Path,
        mqtt_client: Any | None,
        llm_adapter: Any | None,
        memory_store: Any | None,
    ) -> None:
        """Common init body shared by ``__init__`` and ``from_config``."""
        self.config: RegionConfig = config
        self.config_path: Path = Path(config_path)
        self.region_name: str = config.name
        self.region_root: Path = Path(region_root)
        self.phase: LifecyclePhase = LifecyclePhase.BOOTSTRAP

        # Pre-composed modules (filled in bootstrap):
        self.mqtt: Any = mqtt_client
        self.llm: Any = llm_adapter
        self.memory: Any = memory_store
        self.tools: SelfModifyTools | None = None
        self.sleep: SleepCoordinator | None = None
        self.git: GitTools | None = None
        self.heartbeat: Heartbeat | None = None
        self._handlers: list[HandlerModule] = []
        self._ledger: TokenLedger | None = None

        # Dispatch / lifecycle state:
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._shutdown_called: bool = False
        self._log = log.bind(region=self.region_name)
        self._last_inbound_ts: float = time.monotonic()
        # Wake-cycle reference; reset on every transition into WAKE so the
        # sleep_max_wake_s trigger measures time-since-last-wake, not
        # time-since-boot.
        self._wake_start_time: float = time.monotonic()
        # Throttle for the STM-pressure sleep trigger: serializing STM every
        # monitor tick (~10x/s) is wasteful when the store is stable. Check
        # size at most once per _STM_PRESSURE_CHECK_INTERVAL_S.
        self._last_stm_check_ts: float = 0.0

        # Spawn reply correlation:
        self._spawn_futures: dict[str, asyncio.Future[SpawnResult]] = {}

        # Sleep trigger state:
        self._pending_explicit_sleep: str | None = None
        self._sleep_quiet_window_s: float = float(
            config.lifecycle.sleep_quiet_window_s
        )
        self._sleep_max_wake_s: float = float(
            config.lifecycle.sleep_max_wake_s
        )

        # Tracking for heartbeat state_provider:
        self._last_error_ts: str | None = None

        # Tracking for sleep/granted correlation (set by _enter_sleep):
        self._sleep_grant_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def bootstrap(self) -> None:
        """Execute the 10-step §A.4.2 bootstrap sequence.

        Fails fast with typed exceptions:
          * :class:`~region_template.errors.ConfigError` (exit 2)
          * :class:`~region_template.errors.GitError` (exit 3)
          * :class:`~region_template.errors.ConnectionError` (exit 4)
        """
        # Step 1: config already loaded in __init__.
        # Step 2: structlog configuration.
        configure_logging(
            region_name=self.region_name,
            level=self.config.logging.level,
        )

        # Step 3: git init + bootstrap commit.
        self.git = GitTools(self.region_root, region_name=self.region_name)

        # Step 3.5 (not spec-numbered): build TokenLedger + LlmAdapter.
        # Done BEFORE MQTT so a missing ANTHROPIC_API_KEY surfaces as
        # ConfigError before we spend retry budget on the broker.
        if self._ledger is None:
            self._ledger = TokenLedger(self.config.llm.budgets)
        if self.llm is None:
            # This call raises ConfigError if env is missing.
            self.llm = LlmAdapter(
                self.config,
                self.config.capabilities,
                self._ledger,
            )

        # Step 4: MQTT connect (with LWT + backoff inside MqttClient).
        if self.mqtt is None:
            self.mqtt = MqttClient(self.config.mqtt, self.region_name)
        await self.mqtt.__aenter__()

        # Step 5: boot heartbeat (single shot).
        await self._publish_heartbeat_once(status="boot")

        # Step 6: subscriptions.yaml → subscribe. Missing file is OK.
        await self._subscribe_from_yaml()

        # Step 7: mPFC-only bootstrap self/* retained publishes — SKIP for v0.

        # Step 8: discover handlers + subscribe to their topics.
        handlers_dir = self.region_root / "handlers"
        self._handlers = discover(handlers_dir)
        await self._subscribe_from_handlers()

        # Step 9: MemoryStore init.
        if self.memory is None:
            self.memory = MemoryStore(
                root=self.region_root / "memory",
                region_name=self.region_name,
                stm_max_bytes=self.config.memory.stm_max_bytes,
                recent_events_max=self.config.memory.recent_events_max,
                runtime=self,
            )

        # Step 9.5: SelfModifyTools + SleepCoordinator.
        bootstrap_sha = self.git.current_head_sha()
        self.tools = SelfModifyTools(
            region_name=self.region_name,
            region_root=self.region_root,
            capabilities=self.config.capabilities,
            runtime=self,
            git_tools=self.git,
            memory=self.memory,
            bootstrap_sha=bootstrap_sha,
        )
        self.sleep = SleepCoordinator(self)

        # Step 10: WAKE + heartbeat emitter.
        await self._enter_wake()

        # Fire the wake heartbeat once now so tests observing "wake status
        # was published during bootstrap" pass deterministically.
        await self._publish_heartbeat_once(status="wake")

        # Start the periodic heartbeat emitter.
        self.heartbeat = Heartbeat(
            region=self.region_name,
            interval_s=self.config.lifecycle.heartbeat_interval_s,
            publish=self._heartbeat_publish,
            state_provider=self._current_heartbeat_state,
            build_sha=bootstrap_sha,
        )
        await self.heartbeat.start()

    async def run(self) -> None:
        """§A.4.3 — run until ``shutdown`` is called.

        Spawns the message consumer + sleep monitor concurrently. The MQTT
        receive loop (``mqtt.run``) is also started so real clients drain
        the broker queue; fakes make this a no-op.
        """
        if self.phase != LifecyclePhase.WAKE:
            raise RuntimeError(
                f"run() requires WAKE phase, not {self.phase}"
            )

        tasks = [
            asyncio.create_task(self.mqtt.run(), name="mqtt_run"),
            asyncio.create_task(self._sleep_monitor(), name="sleep_monitor"),
        ]
        try:
            await self._shutdown_event.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self, reason: str) -> None:
        """§A.4.6 — graceful teardown. Idempotent; ends in SHUTDOWN."""
        if self._shutdown_called:
            return
        self._shutdown_called = True
        await self._enter_shutdown(reason)

    # ------------------------------------------------------------------
    # Test-only helper
    # ------------------------------------------------------------------

    async def force_sleep(self, reason: str) -> None:
        """TEST-ONLY — simulate an external sleep trigger.

        Production regions receive sleep triggers via the §A.4.5 monitor
        (quiet-window, ``hive/system/sleep/force``, cortisol-low, etc.).
        Tests use this to exercise the sleep transition without wiring up
        the whole trigger surface.
        """
        await self._enter_sleep(trigger="external_command", reason=reason)

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    async def _enter_wake(self) -> None:
        """Switch phase to WAKE. Called from bootstrap and after sleep."""
        self.phase = LifecyclePhase.WAKE
        now = time.monotonic()
        self._last_inbound_ts = now
        # Reset the wake-cycle clock so the ``sleep_max_wake_s`` trigger
        # doesn't fire immediately after a sleep returns to WAKE.
        self._wake_start_time = now

    async def _enter_sleep(
        self, trigger: SleepTrigger, reason: str = ""
    ) -> None:
        """§A.4.4 — sleep entry.

        1. publish ``hive/system/sleep/request``.
        2. wait for ``hive/system/sleep/granted`` (≤60 s).
        3. on grant: phase → SLEEP, bring up SLEEP listener, run
           ``SleepCoordinator.run(trigger)``.
        4. on result:
             * ``no_change`` / ``committed_in_place``: phase → WAKE.
             * ``committed_restart``: run §D.5.5 verify; on pass publish
               ``hive/system/restart/request`` + ``shutdown("restart")``;
               on fail revert the commit + stay WAKE with metacog error.
        """
        if self.phase == LifecyclePhase.SLEEP:
            return  # already sleeping — idempotent
        self._log.info("sleep_entry_begin", trigger=trigger, reason=reason)

        # 1. Publish sleep/request.
        self._sleep_grant_event = asyncio.Event()
        await self.mqtt.publish(
            topic=SYSTEM_SLEEP_REQUEST,
            content_type="application/json",
            data={"region": self.region_name, "reason": reason or trigger},
            qos=1,
            retain=False,
        )

        # Subscribe to sleep/granted if not already.
        await self.mqtt.subscribe(
            SYSTEM_SLEEP_GRANTED, self._on_sleep_granted, qos=1
        )

        # 2. Wait for grant (60 s timeout). If no grant, abort and return to
        # WAKE with a metacog note.
        try:
            await asyncio.wait_for(
                self._sleep_grant_event.wait(),
                timeout=_SLEEP_GRANT_TIMEOUT_S,
            )
        except TimeoutError:
            self._log.warning("sleep_grant_timeout", trigger=trigger)
            await self._publish_metacog_error(
                kind="sleep_grant_timeout",
                detail={"trigger": trigger},
            )
            return  # stay in WAKE

        # 3. Phase → SLEEP; bring up SLEEP listener.
        self.phase = LifecyclePhase.SLEEP
        await self._publish_heartbeat_once(status="sleep")
        await self._subscribe_sleep_phase_listener()

        # 4. Run SleepCoordinator.
        try:
            assert self.sleep is not None
            result = await self.sleep.run(trigger)
        except Exception as exc:  # noqa: BLE001 — coordinator handles own revert
            self._log.error("sleep_coordinator_failed", error=str(exc))
            await self._publish_metacog_error(
                kind="sleep_coordinator_failed",
                detail={"error": str(exc)},
            )
            await self._teardown_sleep_listener()
            await self._enter_wake()
            return

        # 5. Dispatch on result.
        await self._teardown_sleep_listener()
        await self._handle_sleep_result(result)

    async def _handle_sleep_result(self, result: SleepResult) -> None:
        """Process the :class:`SleepResult` from the coordinator."""
        if not result.restart:
            # no_change or committed_in_place — just return to WAKE.
            await self._enter_wake()
            return

        # committed_restart — run pre-restart verify (§D.5.5).
        ok = await self._pre_restart_verify()
        if not ok:
            self._log.warning(
                "pre_restart_verify_failed", sha=result.sha
            )
            # Revert the commit so the broken state doesn't persist.
            if result.sha and self.git is not None:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        self.git.revert_to, f"{result.sha}^"
                    )
            await self._publish_metacog_error(
                kind="pre_restart_verify_failed",
                detail={"sha": result.sha or ""},
            )
            await self._enter_wake()
            return

        # Verify passed — publish restart_request + shutdown exit 0.
        await self.publish_restart_request(
            reason=f"sleep_restart sha={result.sha}"
        )
        await self.shutdown("restart")

    async def _enter_shutdown(self, reason: str) -> None:
        """§A.4.6 — graceful teardown.

        Order matters: stop heartbeat emitter first (so no more publishes
        are scheduled), then publish final heartbeat, then disconnect MQTT.
        """
        self._log.info("shutdown_begin", reason=reason)
        self.phase = LifecyclePhase.SHUTDOWN

        # Stop heartbeat emitter (idempotent).
        if self.heartbeat is not None:
            with contextlib.suppress(Exception):
                await self.heartbeat.stop()

        # Final heartbeat — "sleep_restart" if we're restarting, else
        # "shutdown". Best-effort; MQTT may already be flaky on a crash
        # path, so suppress errors.
        final_status: Any = "sleep_restart" if reason == "restart" else "shutdown"
        with contextlib.suppress(Exception):
            await self._publish_heartbeat_once(status=final_status)

        # Disconnect MQTT cleanly (LWT suppressed by __aexit__).
        if self.mqtt is not None:
            with contextlib.suppress(Exception):
                await self.mqtt.__aexit__(None, None, None)

        self._shutdown_event.set()
        self._log.info("shutdown_complete", reason=reason)

    # ------------------------------------------------------------------
    # MQTT-side dispatch helpers
    # ------------------------------------------------------------------

    async def _on_message(self, envelope: Envelope) -> None:
        """Inbound MQTT callback registered by ``_subscribe_from_handlers``."""
        self._last_inbound_ts = time.monotonic()
        await self._dispatch(envelope)

    async def _dispatch(self, envelope: Envelope) -> None:
        """§A.4.3 — match handlers, enforce timeout, publish metacog on error."""
        if self.phase != LifecyclePhase.WAKE:
            # During SLEEP the normal consumer is torn down. Messages that
            # leak through (e.g. via a fake that still delivers) are dropped.
            return

        handlers = match_handlers_for_topic(self._handlers, envelope.topic)
        if not handlers:
            return

        ctx = self._build_handler_context()
        for h in handlers:
            try:
                async with asyncio.timeout(h.timeout_s):
                    await h.handle(envelope, ctx)
            except TimeoutError:
                await self._publish_metacog_error(
                    kind="handler_timeout",
                    detail={
                        "handler": h.name,
                        "topic": envelope.topic,
                        "timeout_s": h.timeout_s,
                    },
                )
            except Exception as exc:  # noqa: BLE001 — handler boundary
                await self._publish_metacog_error(
                    kind="handler_crash",
                    detail={
                        "handler": h.name,
                        "topic": envelope.topic,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )

    def _build_handler_context(self) -> HandlerContext:
        """Construct a :class:`HandlerContext` for dispatch."""
        return HandlerContext(
            region_name=self.region_name,
            phase=self.phase,
            publish=self.mqtt.publish,
            llm=self.llm,
            memory=self.memory,
            tools=self.tools,  # type: ignore[arg-type]
            request_sleep=self._request_sleep,
            log=self._log,
        )

    def _request_sleep(self, reason: str) -> None:
        """Callable handed to handlers as ``ctx.request_sleep``.

        Records an explicit sleep request. The next ``_sleep_monitor`` tick
        picks it up.
        """
        self._pending_explicit_sleep = reason

    # ------------------------------------------------------------------
    # Sleep monitor (§A.4.5)
    # ------------------------------------------------------------------

    async def _sleep_monitor(self) -> None:
        """Watch §A.4.5 triggers. At most one trigger per transition.

        Triggers checked each tick:
          * explicit request via ``ctx.request_sleep``
          * quiet window (no inbound for ``sleep_quiet_window_s``)
          * heartbeat cycle (every ``sleep_max_wake_s``)
          * STM pressure (size > ``stm_max_bytes``)

        External-command triggers come in via the ``hive/system/sleep/force``
        subscription, handled by ``_on_sleep_force`` which calls
        ``_enter_sleep`` directly.
        """
        # Subscribe to sleep/force at monitor startup.
        with contextlib.suppress(Exception):
            await self.mqtt.subscribe(
                SYSTEM_SLEEP_FORCE, self._on_sleep_force, qos=1
            )

        while not self._shutdown_event.is_set():
            try:
                if self.phase != LifecyclePhase.WAKE:
                    await asyncio.sleep(_SLEEP_MONITOR_TICK_S)
                    continue

                trigger = self._check_sleep_triggers()
                if trigger is not None:
                    trigger_kind, reason = trigger
                    # Clear pending explicit before dispatching.
                    if trigger_kind == "explicit_request":
                        self._pending_explicit_sleep = None
                    await self._enter_sleep(trigger_kind, reason=reason)

                await asyncio.sleep(_SLEEP_MONITOR_TICK_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.error("sleep_monitor_error", error=str(exc))
                await asyncio.sleep(_SLEEP_MONITOR_TICK_S)

    def _check_sleep_triggers(self) -> tuple[SleepTrigger, str] | None:
        """Return (trigger, reason) for the first matching trigger, or None."""
        now = time.monotonic()
        # 1. Explicit request (highest priority; set by ctx.request_sleep).
        if self._pending_explicit_sleep is not None:
            return (
                "explicit_request",
                self._pending_explicit_sleep,
            )

        # 2. Quiet window.
        if self._sleep_quiet_window_s > 0 and (
            now - self._last_inbound_ts
        ) >= self._sleep_quiet_window_s:
            return (
                "quiet_window",
                f"no inbound for {self._sleep_quiet_window_s:.0f}s",
            )

        # 3. Heartbeat cycle (max_wake). Measured from last wake transition
        # so a short-cycle region doesn't thrash in/out of sleep.
        if self._sleep_max_wake_s > 0 and (
            now - self._wake_start_time
        ) >= self._sleep_max_wake_s:
            return (
                "heartbeat_cycle",
                f"awake for {self._sleep_max_wake_s:.0f}s",
            )

        # 4. STM pressure — size is expensive to compute (JSON serialize),
        # so throttle to at most once per _STM_PRESSURE_CHECK_INTERVAL_S.
        if (
            self.memory is not None
            and (now - self._last_stm_check_ts)
            >= _STM_PRESSURE_CHECK_INTERVAL_S
        ):
            self._last_stm_check_ts = now
            with contextlib.suppress(Exception):
                # list_stm/recent_events are async; _serialize is the cheap
                # sync proxy that powers list_stm/stm_size_bytes internally.
                size = len(self.memory._serialize())
                if size > self.config.memory.stm_max_bytes:
                    return (
                        "stm_pressure",
                        f"stm size {size} > {self.config.memory.stm_max_bytes}",
                    )

        return None

    # ------------------------------------------------------------------
    # Message callbacks — subscribed during bootstrap / sleep entry
    # ------------------------------------------------------------------

    async def _on_sleep_granted(self, envelope: Envelope) -> None:
        """Handler for ``hive/system/sleep/granted``.

        Sets the grant event so ``_enter_sleep`` proceeds. Matches on region
        name when present in the payload; otherwise accepts blindly.
        """
        data = envelope.payload.data if envelope.payload else {}
        # Accept if data.region is absent OR matches ours.
        if isinstance(data, dict):
            target = data.get("region")
            if target is not None and target != self.region_name:
                return
        if self._sleep_grant_event is not None:
            self._sleep_grant_event.set()
        await self._on_sleep_request_accepted()

    async def _on_sleep_request_accepted(self) -> None:
        """Hook for subclasses; default is a no-op."""
        return

    async def _on_sleep_force(self, envelope: Envelope) -> None:
        """Handler for ``hive/system/sleep/force``.

        Triggers an external-command sleep if the payload's region matches
        ours (or is absent).
        """
        data = envelope.payload.data if envelope.payload else {}
        reason = "sleep_force"
        if isinstance(data, dict):
            target = data.get("region")
            if target is not None and target != self.region_name:
                return
            reason = data.get("reason") or reason
        if self.phase == LifecyclePhase.WAKE:
            # Schedule the sleep transition; don't block this callback.
            asyncio.create_task(
                self._enter_sleep("external_command", reason=reason)
            )

    async def _on_spawn_reply(self, envelope: Envelope) -> None:
        """Handler for ``hive/system/spawn/complete|failed`` — resolve the
        future registered by :meth:`publish_spawn_request`."""
        corr = envelope.correlation_id
        if corr is None:
            return
        future = self._spawn_futures.pop(corr, None)
        if future is None or future.done():
            return
        data = envelope.payload.data if envelope.payload else {}
        ok = bool(data.get("ok", False)) if isinstance(data, dict) else False
        sha = (
            str(data.get("sha"))
            if isinstance(data, dict) and data.get("sha")
            else None
        )
        reason = (
            str(data.get("reason"))
            if isinstance(data, dict) and data.get("reason")
            else None
        )
        future.set_result(SpawnResult(ok=ok, sha=sha, reason=reason))

    # ------------------------------------------------------------------
    # SLEEP-phase listener (§A.4.4.1)
    # ------------------------------------------------------------------

    async def _subscribe_sleep_phase_listener(self) -> None:
        """Add subscriptions for the narrow SLEEP-phase topic set.

        Only framework topics; handler dispatch is suspended during SLEEP.
        Spawn replies are already subscribed at bootstrap.
        """
        with contextlib.suppress(Exception):
            await self.mqtt.subscribe(
                MODULATOR_CORTISOL, self._on_cortisol_during_sleep, qos=1
            )
        with contextlib.suppress(Exception):
            await self.mqtt.subscribe(
                BROADCAST_SHUTDOWN, self._on_broadcast_shutdown, qos=1
            )

    async def _teardown_sleep_listener(self) -> None:
        """Remove the extra SLEEP-phase subscriptions."""
        with contextlib.suppress(Exception):
            await self.mqtt.unsubscribe(
                MODULATOR_CORTISOL, self._on_cortisol_during_sleep
            )
        with contextlib.suppress(Exception):
            await self.mqtt.unsubscribe(
                BROADCAST_SHUTDOWN, self._on_broadcast_shutdown
            )

    async def _on_cortisol_during_sleep(self, envelope: Envelope) -> None:
        """If cortisol spikes during sleep, tell SleepCoordinator to abort."""
        if self.phase != LifecyclePhase.SLEEP:
            return
        data = envelope.payload.data if envelope.payload else {}
        level = 0.0
        if isinstance(data, dict):
            with contextlib.suppress(TypeError, ValueError):
                level = float(data.get("level", 0.0))
        threshold = self.config.lifecycle.sleep_abort_cortisol_threshold
        if level >= threshold and self.sleep is not None:
            await self.sleep.abort(
                reason=f"cortisol {level} >= {threshold}"
            )

    async def _on_broadcast_shutdown(self, envelope: Envelope) -> None:
        """``hive/broadcast/shutdown`` — graceful shutdown request."""
        await self.shutdown("broadcast_shutdown")

    # ------------------------------------------------------------------
    # Subscription helpers
    # ------------------------------------------------------------------

    async def _subscribe_from_yaml(self) -> None:
        """Step 6: read subscriptions.yaml; subscribe each row at declared QoS.

        Missing file is legal — many regions rely solely on handler-declared
        subscriptions. Malformed content is skipped with a WARN.
        """
        subs_path = self.region_root / "subscriptions.yaml"
        if not subs_path.exists():
            return

        try:
            yaml = YAML(typ="safe")
            with subs_path.open("r", encoding="utf-8") as f:
                data = yaml.load(f)
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "subscriptions_yaml_parse_failed", error=str(exc)
            )
            return

        if not isinstance(data, list):
            self._log.warning(
                "subscriptions_yaml_not_a_list",
                got_type=type(data).__name__,
            )
            return

        for row in data:
            if not isinstance(row, dict):
                continue
            topic = row.get("topic")
            qos = int(row.get("qos", 1))
            if not isinstance(topic, str) or not topic:
                continue
            with contextlib.suppress(Exception):
                await self.mqtt.subscribe(topic, self._on_message, qos=qos)

    async def _subscribe_from_handlers(self) -> None:
        """Subscribe to every topic declared by every discovered handler."""
        for h in self._handlers:
            for topic_filter in h.subscriptions:
                with contextlib.suppress(Exception):
                    await self.mqtt.subscribe(
                        topic_filter, self._on_message, qos=h.qos
                    )
        # Also subscribe to spawn replies so publish_spawn_request can
        # resolve its futures.
        with contextlib.suppress(Exception):
            await self.mqtt.subscribe(
                SYSTEM_SPAWN_COMPLETE, self._on_spawn_reply, qos=1
            )
        with contextlib.suppress(Exception):
            await self.mqtt.subscribe(
                SYSTEM_SPAWN_FAILED, self._on_spawn_reply, qos=1
            )

    # ------------------------------------------------------------------
    # Runtime protocol methods (for SelfModifyTools + SleepCoordinator)
    # ------------------------------------------------------------------

    async def publish_restart_request(self, reason: str) -> None:
        """Publish ``hive/system/restart/request`` for glia to observe."""
        await self.mqtt.publish(
            topic=SYSTEM_RESTART_REQUEST,
            content_type="application/json",
            data={"region": self.region_name, "reason": reason},
            qos=1,
            retain=False,
        )

    async def publish_spawn_request(
        self, proposal: SpawnProposal, correlation_id: str
    ) -> asyncio.Future[SpawnResult]:
        """Publish ``hive/system/spawn/request``; register correlation future.

        The returned future resolves when a matching
        ``hive/system/spawn/complete`` or ``…/failed`` envelope arrives.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SpawnResult] = loop.create_future()
        self._spawn_futures[correlation_id] = future

        # Serialize proposal for the envelope payload.
        data = _serialize_spawn_proposal(proposal)
        await self.mqtt.publish(
            topic=SYSTEM_SPAWN_REQUEST,
            content_type="application/hive+spawn-request",
            data=data,
            correlation_id=correlation_id,
            qos=1,
            retain=False,
        )
        return future

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_publish(self, envelope: Envelope) -> None:
        """Adapter from :class:`Heartbeat`'s ``publish(envelope)`` contract
        to :class:`MqttClient.publish`'s kwargs-based API."""
        await self.mqtt.publish(
            topic=envelope.topic,
            content_type=envelope.payload.content_type,
            data=envelope.payload.data,
            encoding=envelope.payload.encoding,
            qos=1,
            retain=False,
        )

    def _current_heartbeat_state(self) -> HeartbeatState:
        """Build a :class:`HeartbeatState` snapshot from runtime counters."""
        # Best-effort LLM lifetime count: ledger hour values understate
        # lifetime but track the right direction. Post-v0 can add a true
        # monotonic counter.
        tokens_used = 0
        if self._ledger is not None:
            u = self._ledger.effective_usage()
            tokens_used = u.input_hour + u.output_hour

        stm_bytes = 0
        if self.memory is not None:
            with contextlib.suppress(Exception):
                stm_bytes = len(self.memory._serialize())

        # Map phase → status. 'sleep_restart' is set only in _enter_shutdown
        # when reason == 'restart' (handled by _publish_heartbeat_once).
        if self.phase == LifecyclePhase.SLEEP:
            status: Any = "sleep"
        elif self.phase == LifecyclePhase.SHUTDOWN:
            status = "shutdown"
        elif self.phase == LifecyclePhase.BOOTSTRAP:
            status = "boot"
        else:
            status = "wake"

        return HeartbeatState(
            status=status,
            phase=self.phase,
            handler_count=len(self._handlers),
            queue_depth_messages=0,
            llm_tokens_used_lifetime=tokens_used,
            stm_bytes=stm_bytes,
            last_error_ts=self._last_error_ts,
        )

    async def _publish_heartbeat_once(self, status: str) -> None:
        """Publish a single heartbeat envelope with the given status.

        Used for the boot/wake/sleep/shutdown single-shot publishes that
        don't come from :class:`Heartbeat`'s periodic tick.
        """
        topic = fill(SYSTEM_HEARTBEAT, region=self.region_name)
        data = {
            "region": self.region_name,
            "status": status,
            "phase": str(self.phase),
            "handler_count": len(self._handlers),
        }
        with contextlib.suppress(Exception):
            await self.mqtt.publish(
                topic=topic,
                content_type="application/json",
                data=data,
                qos=1,
                retain=False,
            )

    # ------------------------------------------------------------------
    # Metacog error helper
    # ------------------------------------------------------------------

    async def _publish_metacog_error(
        self, *, kind: str, detail: dict[str, Any]
    ) -> None:
        """Publish a ``hive/metacognition/error/detected`` envelope.

        Best-effort — we don't want a broken metacog publish to mask the
        original error the caller is reporting.
        """
        self._last_error_ts = _now_iso()
        payload = {"kind": kind, **detail}
        with contextlib.suppress(Exception):
            await self.mqtt.publish(
                topic=METACOGNITION_ERROR_DETECTED,
                content_type="application/hive+error",
                data=payload,
                qos=1,
                retain=False,
            )

    # ------------------------------------------------------------------
    # Pre-restart verification (§D.5.5)
    # ------------------------------------------------------------------

    async def _pre_restart_verify(self) -> bool:
        """Dry-import the runtime in a subprocess. Return True on success.

        Spec §D.5.5: verifies the committed code still imports cleanly
        before we ask glia to restart us. Subprocess call is wrapped in
        ``asyncio.to_thread`` so it doesn't block the event loop.
        """
        code = (
            "from region_template.runtime import RegionRuntime; "
            "from pathlib import Path; "
            f"RegionRuntime(Path({str(self.config_path)!r}))"
        )
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", code],
                capture_output=True,
                timeout=_PRE_RESTART_VERIFY_TIMEOUT_S,
                check=False,
            )
            return result.returncode == 0
        except Exception as exc:  # noqa: BLE001
            self._log.warning("pre_restart_verify_exception", error=str(exc))
            return False


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _serialize_spawn_proposal(proposal: SpawnProposal) -> dict[str, Any]:
    """Serialize a :class:`SpawnProposal` for an envelope payload."""
    caps = proposal.capabilities
    if isinstance(caps, CapabilityProfile):
        caps_dict = caps.model_dump()
    else:
        caps_dict = dict(caps) if isinstance(caps, dict) else {}
    return {
        "name": proposal.name,
        "role": proposal.role,
        "modality": proposal.modality,
        "llm": dict(proposal.llm),
        "capabilities": caps_dict,
        "starter_prompt": proposal.starter_prompt,
        "initial_subscriptions": [
            dataclasses.asdict(entry)
            for entry in proposal.initial_subscriptions
        ],
    }


def _now_iso() -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
