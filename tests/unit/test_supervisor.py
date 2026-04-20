"""Unit tests for glia.supervisor — Task 5.9.

Every sub-module is mocked; the clock and sleeper are injected so the tests
are deterministic and do not sleep.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from glia.acl_manager import AclManager
from glia.codechange_executor import CodeChangeExecutor
from glia.heartbeat_monitor import HeartbeatMonitor
from glia.launcher import GliaError, Launcher
from glia.metrics import MetricsAggregator
from glia.registry import RegionRegistry
from glia.rollback import Rollback, RollbackResult
from glia.spawn_executor import SpawnExecutor
from glia.supervisor import (
    BACKOFF_CAP_S,
    PLANNED_RESTART_PAUSE_S,
    Supervisor,
)
from shared.message_envelope import Envelope
from shared.topics import METACOGNITION_ERROR_DETECTED, SYSTEM_SLEEP_GRANTED

# ---------------------------------------------------------------------------
# Constants (keep ruff PLR2004 quiet)
# ---------------------------------------------------------------------------
EXPECTED_FIRST_BACKOFF = 5.0
EXPECTED_SECOND_BACKOFF = 15.0
CRASH_THRESHOLD = 5
EXPECTED_RELAUNCH_CALLS_AFTER_FIVE_SAFE_CRASHES = 4  # 5th trips, no restart
BACKOFF_SEQUENCE = (5.0, 15.0, 45.0, 90.0, 180.0, 300.0)
HEALTHY_CRASH_COUNT = 4
TIME_AFTER_WINDOW_S = 700.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Clock:
    """Mutable wall clock for tests — use ``now += 1.0`` to advance."""

    def __init__(self, t: float = 0.0) -> None:
        self.now = t

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock(0.0)


@pytest.fixture
def sleeper() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def publish() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def sub_mocks() -> dict[str, Any]:
    return {
        "registry": MagicMock(spec=RegionRegistry),
        "launcher": MagicMock(spec=Launcher),
        "heartbeat_monitor": MagicMock(spec=HeartbeatMonitor),
        "acl_manager": MagicMock(spec=AclManager),
        "rollback": AsyncMock(spec=Rollback),
        "spawn_executor": AsyncMock(spec=SpawnExecutor),
        "codechange_executor": AsyncMock(spec=CodeChangeExecutor),
        "metrics": MagicMock(spec=MetricsAggregator),
    }


@pytest.fixture
def supervisor(
    sub_mocks: dict[str, Any],
    publish: AsyncMock,
    clock: _Clock,
    sleeper: AsyncMock,
) -> Supervisor:
    # HeartbeatMonitor / Metrics async methods need AsyncMock replacements
    # because MagicMock(spec=) doesn't auto-produce awaitables.
    sub_mocks["heartbeat_monitor"].on_heartbeat = AsyncMock()
    sub_mocks["heartbeat_monitor"].start = AsyncMock()
    sub_mocks["heartbeat_monitor"].stop = AsyncMock()
    sub_mocks["metrics"].on_region_stats = AsyncMock()
    sub_mocks["metrics"].start = AsyncMock()
    sub_mocks["metrics"].stop = AsyncMock()
    return Supervisor(
        sub_mocks["registry"],
        sub_mocks["launcher"],
        sub_mocks["heartbeat_monitor"],
        sub_mocks["acl_manager"],
        sub_mocks["rollback"],
        sub_mocks["spawn_executor"],
        sub_mocks["codechange_executor"],
        sub_mocks["metrics"],
        publish=publish,
        clock=clock,
        sleeper=sleeper,
    )


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _heartbeat_env(region: str = "amygdala") -> Envelope:
    return Envelope.new(
        source_region=region,
        topic=f"hive/system/heartbeat/{region}",
        content_type="application/json",
        data={"region": region, "status": "alive"},
    )


def _region_stats_env(region: str = "amygdala") -> Envelope:
    return Envelope.new(
        source_region=region,
        topic=f"hive/system/region_stats/{region}",
        content_type="application/json",
        data={"region": region, "tokens_in": 1, "tokens_out": 2},
    )


def _sleep_request_env(
    region: str = "amygdala", corr: str = "corr-sleep"
) -> Envelope:
    return Envelope.new(
        source_region=region,
        topic="hive/system/sleep/request",
        content_type="application/json",
        data={"region": region, "reason": "stm_pressure"},
        correlation_id=corr,
    )


def _restart_request_env(region: str = "amygdala") -> Envelope:
    return Envelope.new(
        source_region=region,
        topic="hive/system/restart/request",
        content_type="application/json",
        data={"region": region},
    )


def _spawn_request_env() -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic="hive/system/spawn/request",
        content_type="application/hive+spawn-request",
        data={"name": "new_region"},
    )


def _spawn_query_env() -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic="hive/system/spawn/query",
        content_type="application/json",
        data={},
    )


def _codechange_env() -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic="hive/system/codechange/approved",
        content_type="application/json",
        data={"change_id": "abc"},
    )


# ---------------------------------------------------------------------------
# 1. Routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_heartbeat_forwards_to_monitor(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _heartbeat_env()
    await supervisor.on_heartbeat(env)
    sub_mocks["heartbeat_monitor"].on_heartbeat.assert_awaited_once_with(
        env, retained=False
    )


@pytest.mark.asyncio
async def test_on_heartbeat_propagates_retained_flag(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _heartbeat_env()
    await supervisor.on_heartbeat(env, retained=True)
    sub_mocks["heartbeat_monitor"].on_heartbeat.assert_awaited_once_with(
        env, retained=True
    )


@pytest.mark.asyncio
async def test_on_region_stats_forwards_to_metrics(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _region_stats_env()
    await supervisor.on_region_stats(env)
    sub_mocks["metrics"].on_region_stats.assert_awaited_once_with(env)


@pytest.mark.asyncio
async def test_on_spawn_request_delegates(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _spawn_request_env()
    await supervisor.on_spawn_request(env)
    sub_mocks["spawn_executor"].handle_request.assert_awaited_once_with(env)


@pytest.mark.asyncio
async def test_on_spawn_query_delegates(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _spawn_query_env()
    await supervisor.on_spawn_query(env)
    sub_mocks["spawn_executor"].handle_query.assert_awaited_once_with(env)


@pytest.mark.asyncio
async def test_on_codechange_approved_delegates(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _codechange_env()
    await supervisor.on_codechange_approved(env)
    sub_mocks["codechange_executor"].apply_change.assert_awaited_once_with(env)


# ---------------------------------------------------------------------------
# 2. Sleep / Restart requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_sleep_request_publishes_granted(
    supervisor: Supervisor, publish: AsyncMock
) -> None:
    env = _sleep_request_env(region="amygdala", corr="corr-1")
    await supervisor.on_sleep_request(env)
    publish.assert_awaited_once()
    (published_env,) = publish.call_args.args
    assert published_env.topic == SYSTEM_SLEEP_GRANTED
    assert published_env.correlation_id == "corr-1"
    assert published_env.payload.data == {"region": "amygdala"}


@pytest.mark.asyncio
async def test_sleep_granted_v0_unconditional(
    supervisor: Supervisor, publish: AsyncMock
) -> None:
    """v0 simplification: every sleep request is granted.

    This test locks the v0 behaviour — if a future pass introduces resource
    gating this test must be updated to reflect the new arbitration.
    """
    env = _sleep_request_env()
    await supervisor.on_sleep_request(env)
    assert publish.await_count == 1


@pytest.mark.asyncio
async def test_on_restart_request_stops_and_launches(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    env = _restart_request_env(region="amygdala")
    await supervisor.on_restart_request(env)
    sub_mocks["launcher"].stop_region.assert_called_once_with("amygdala")
    sub_mocks["launcher"].launch_region.assert_called_once_with("amygdala")


@pytest.mark.asyncio
async def test_on_restart_request_swallows_glia_error(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    sub_mocks["launcher"].stop_region.side_effect = GliaError("boom")
    env = _restart_request_env()
    # Must not raise.
    await supervisor.on_restart_request(env)


# ---------------------------------------------------------------------------
# 3. Docker-exit path — planned (exit 0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_region_exit_0_restarts_after_pause(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
    publish: AsyncMock,
) -> None:
    await supervisor.on_region_exit("amygdala", 0)
    sleeper.assert_awaited_once_with(PLANNED_RESTART_PAUSE_S)
    sub_mocks["launcher"].restart_region.assert_called_once_with("amygdala")
    sub_mocks["rollback"].rollback_region.assert_not_awaited()
    # No metacog for a planned exit.
    for call in publish.await_args_list:
        (env,) = call.args
        assert env.topic != METACOGNITION_ERROR_DETECTED


# ---------------------------------------------------------------------------
# 4. Docker-exit path — transient (exit 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_region_exit_1_records_crash_and_restarts_with_backoff(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
) -> None:
    await supervisor.on_region_exit("amygdala", 1)
    sleeper.assert_awaited_once_with(EXPECTED_FIRST_BACKOFF)
    sub_mocks["launcher"].restart_region.assert_called_once_with("amygdala")
    sub_mocks["rollback"].rollback_region.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_region_exit_4_treated_as_transient(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
) -> None:
    await supervisor.on_region_exit("amygdala", 4)
    sleeper.assert_awaited_once_with(EXPECTED_FIRST_BACKOFF)
    sub_mocks["launcher"].restart_region.assert_called_once_with("amygdala")


@pytest.mark.asyncio
async def test_on_region_exit_137_treated_as_transient(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
) -> None:
    await supervisor.on_region_exit("amygdala", 137)
    sleeper.assert_awaited_once_with(EXPECTED_FIRST_BACKOFF)
    sub_mocks["launcher"].restart_region.assert_called_once_with("amygdala")


# ---------------------------------------------------------------------------
# 5. Backoff schedule progression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_schedule_progression(
    sub_mocks: dict[str, Any], publish: AsyncMock, clock: _Clock
) -> None:
    """6 successive exit-1 events span the schedule + the cap.

    Use a custom crash_threshold so the 5th+ crashes still attempt restart
    (default threshold=5 would trip after the 5th). Here we set the threshold
    beyond the test run so we can observe the full schedule.
    """
    sleeper = AsyncMock()
    # Use AsyncMock replacements for async sub-module methods.
    sub_mocks["heartbeat_monitor"].on_heartbeat = AsyncMock()
    sub_mocks["heartbeat_monitor"].start = AsyncMock()
    sub_mocks["heartbeat_monitor"].stop = AsyncMock()
    sub_mocks["metrics"].on_region_stats = AsyncMock()
    sub_mocks["metrics"].start = AsyncMock()
    sub_mocks["metrics"].stop = AsyncMock()

    sup = Supervisor(
        sub_mocks["registry"],
        sub_mocks["launcher"],
        sub_mocks["heartbeat_monitor"],
        sub_mocks["acl_manager"],
        sub_mocks["rollback"],
        sub_mocks["spawn_executor"],
        sub_mocks["codechange_executor"],
        sub_mocks["metrics"],
        publish=publish,
        clock=clock,
        sleeper=sleeper,
        crash_threshold=100,  # disable circuit breaker for this test
    )

    for i in range(len(BACKOFF_SEQUENCE)):
        # Advance clock beyond the 10-minute window so the window-trim
        # check doesn't interact with the schedule test.
        clock.now = float(i) * 0.001  # tiny advance; within window anyway
        await sup.on_region_exit("amygdala", 1)

    observed = [call.args[0] for call in sleeper.await_args_list]
    assert tuple(observed) == BACKOFF_SEQUENCE
    # Final backoff equals the cap.
    assert observed[-1] == BACKOFF_CAP_S


# ---------------------------------------------------------------------------
# 6. Exit 2 / 3 → rollback, not restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_region_exit_2_triggers_rollback(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    publish: AsyncMock,
) -> None:
    sub_mocks["rollback"].rollback_region.return_value = RollbackResult(
        ok=True, reverted_to="abc123"
    )
    await supervisor.on_region_exit("amygdala", 2)
    sub_mocks["rollback"].rollback_region.assert_awaited_once_with(
        "amygdala", "exit_2"
    )
    sub_mocks["launcher"].restart_region.assert_not_called()

    # One metacog event with kind=region_config_error.
    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "region_config_error" in metacog_kinds


@pytest.mark.asyncio
async def test_on_region_exit_3_triggers_rollback(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    publish: AsyncMock,
) -> None:
    sub_mocks["rollback"].rollback_region.return_value = RollbackResult(
        ok=True, reverted_to="xyz789"
    )
    await supervisor.on_region_exit("amygdala", 3)
    sub_mocks["rollback"].rollback_region.assert_awaited_once_with(
        "amygdala", "exit_3"
    )
    sub_mocks["launcher"].restart_region.assert_not_called()

    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "region_git_error" in metacog_kinds


@pytest.mark.asyncio
async def test_rollback_failure_publishes_rollback_failed_metacog(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    publish: AsyncMock,
) -> None:
    sub_mocks["rollback"].rollback_region.return_value = RollbackResult(
        ok=False, reason="no parent commit"
    )
    await supervisor.on_region_exit("amygdala", 2)
    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "rollback_failed" in metacog_kinds


@pytest.mark.asyncio
async def test_rollback_raising_publishes_rollback_failed_metacog(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    publish: AsyncMock,
) -> None:
    sub_mocks["rollback"].rollback_region.side_effect = RuntimeError("boom")
    await supervisor.on_region_exit("amygdala", 3)
    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "rollback_failed" in metacog_kinds


# ---------------------------------------------------------------------------
# 7. Crash-loop circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crash_loop_trips_after_threshold(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
    publish: AsyncMock,
    clock: _Clock,
) -> None:
    # 5 crashes @ t=0..4 (default threshold=5, window=600s).
    for i in range(CRASH_THRESHOLD):
        clock.now = float(i)
        await supervisor.on_region_exit("amygdala", 1)

    # 5th crash trips — no 5th restart, no 5th sleeper call.
    assert (
        sub_mocks["launcher"].restart_region.call_count
        == EXPECTED_RELAUNCH_CALLS_AFTER_FIVE_SAFE_CRASHES
    )

    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "crash_loop" in metacog_kinds

    # 6th crash: circuit still broken, no further restart.
    clock.now = 5.0
    await supervisor.on_region_exit("amygdala", 1)
    assert (
        sub_mocks["launcher"].restart_region.call_count
        == EXPECTED_RELAUNCH_CALLS_AFTER_FIVE_SAFE_CRASHES
    )


@pytest.mark.asyncio
async def test_crash_window_expires_old_entries(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
    clock: _Clock,
    publish: AsyncMock,
) -> None:
    # 4 crashes @ t=0..3 — none trip.
    for i in range(HEALTHY_CRASH_COUNT):
        clock.now = float(i)
        await supervisor.on_region_exit("amygdala", 1)

    # Jump beyond the 600s window, crash once more — old entries trimmed,
    # current window count is 1, circuit NOT broken.
    clock.now = TIME_AFTER_WINDOW_S
    await supervisor.on_region_exit("amygdala", 1)

    metacog_kinds = [
        call.args[0].payload.data["kind"]
        for call in publish.await_args_list
        if call.args[0].topic == METACOGNITION_ERROR_DETECTED
    ]
    assert "crash_loop" not in metacog_kinds


# ---------------------------------------------------------------------------
# 8. Heartbeat callbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_region_unhealthy_triggers_restart_with_backoff(
    supervisor: Supervisor,
    sub_mocks: dict[str, Any],
    sleeper: AsyncMock,
) -> None:
    await supervisor._handle_region_unhealthy("amygdala", reason="miss_threshold")
    sleeper.assert_awaited_once_with(EXPECTED_FIRST_BACKOFF)
    sub_mocks["launcher"].restart_region.assert_called_once_with("amygdala")
    # Rollback NOT invoked — heartbeat miss is not a §E.5 trigger.
    sub_mocks["rollback"].rollback_region.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_region_healthy_clears_circuit_breaker(
    supervisor: Supervisor,
) -> None:
    supervisor._circuit_broken.add("amygdala")
    await supervisor._handle_region_healthy("amygdala")
    assert "amygdala" not in supervisor._circuit_broken


@pytest.mark.asyncio
async def test_handle_region_healthy_does_not_reset_crash_count(
    supervisor: Supervisor, clock: _Clock
) -> None:
    # Induce one crash.
    await supervisor.on_region_exit("amygdala", 1)
    assert supervisor._state["amygdala"].crash_count == 1
    await supervisor._handle_region_healthy("amygdala")
    assert supervisor._state["amygdala"].crash_count == 1


# ---------------------------------------------------------------------------
# 9. start/stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_wires_callbacks_and_starts_loops(
    sub_mocks: dict[str, Any], publish: AsyncMock, clock: _Clock, sleeper: AsyncMock
) -> None:
    # Use a real HeartbeatMonitor so we can inspect its private attributes
    # without MagicMock's auto-wrapping obscuring identity.
    real_hbm = HeartbeatMonitor()
    sub_mocks["metrics"].on_region_stats = AsyncMock()
    sub_mocks["metrics"].start = AsyncMock()
    sub_mocks["metrics"].stop = AsyncMock()
    sup = Supervisor(
        sub_mocks["registry"],
        sub_mocks["launcher"],
        real_hbm,
        sub_mocks["acl_manager"],
        sub_mocks["rollback"],
        sub_mocks["spawn_executor"],
        sub_mocks["codechange_executor"],
        sub_mocks["metrics"],
        publish=publish,
        clock=clock,
        sleeper=sleeper,
    )
    try:
        await sup.start()
        assert real_hbm._on_unhealthy == sup._handle_region_unhealthy
        assert real_hbm._on_healthy == sup._handle_region_healthy
        sub_mocks["metrics"].start.assert_awaited_once_with()
    finally:
        await sup.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    await supervisor.start()
    await supervisor.start()
    assert sub_mocks["heartbeat_monitor"].start.await_count == 1
    assert sub_mocks["metrics"].start.await_count == 1


@pytest.mark.asyncio
async def test_stop_is_idempotent(
    supervisor: Supervisor, sub_mocks: dict[str, Any]
) -> None:
    await supervisor.start()
    await supervisor.stop()
    await supervisor.stop()
    assert sub_mocks["heartbeat_monitor"].stop.await_count == 1
    assert sub_mocks["metrics"].stop.await_count == 1


@pytest.mark.asyncio
async def test_stop_without_start_is_noop(supervisor: Supervisor) -> None:
    # Must not raise even if never started.
    await supervisor.stop()


# ---------------------------------------------------------------------------
# 10. Reset crash counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_crash_counter_clears_state(
    supervisor: Supervisor, clock: _Clock
) -> None:
    await supervisor.on_region_exit("amygdala", 1)
    assert supervisor._state["amygdala"].crash_count == 1
    supervisor._circuit_broken.add("amygdala")
    supervisor.reset_crash_counter("amygdala")
    assert "amygdala" not in supervisor._state
    assert "amygdala" not in supervisor._circuit_broken
