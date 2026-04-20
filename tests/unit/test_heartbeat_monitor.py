"""Tests for glia.heartbeat_monitor — spec §E.3.

Passive liveness tracker. Ingests heartbeat envelopes via on_heartbeat();
sweep loop increments miss counters; LWT (retained dead) and miss-threshold
exceedance both fire on_unhealthy. Recovery fires on_healthy.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from glia.heartbeat_monitor import (
    DEFAULT_MAX_MISSES,
    DEFAULT_MISS_THRESHOLD_S,
    HeartbeatMonitor,
    RegionLiveness,
)
from shared.message_envelope import Envelope

# Test-local constants (avoid magic-value comparisons).
_CLOCK_START = 100.0
_UPTIME_A = 17
_QUEUE_DEPTH_A = 4
_UPTIME_B = 50
_CLOCK_AFTER_RESET = 150.0
_QUEUE_DEPTH_B = 7
_UPTIME_C = 99


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hb_envelope(
    region: str = "amygdala",
    *,
    status: str = "wake",
    phase: str = "wake",
    uptime_s: int = 10,
    queue_depth: int = 2,
    build_sha: str | None = "abc1234",
    extra: dict[str, Any] | None = None,
) -> Envelope:
    data: dict[str, Any] = {
        "region": region,
        "status": status,
        "phase": phase,
        "ts": "2026-04-19T10:30:00.123Z",
        "uptime_s": uptime_s,
        "handler_count": 3,
        "queue_depth_messages": queue_depth,
        "llm_tokens_used_lifetime": 12345,
        "stm_bytes": 4096,
        "last_error_ts": None,
        "build_sha": build_sha,
    }
    if extra:
        data.update(extra)
    return Envelope.new(
        source_region=region,
        topic=f"hive/system/heartbeat/{region}",
        content_type="application/json",
        data=data,
    )


class _Clock:
    """Mutable monotonic clock for deterministic tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


class _RecordingUnhealthy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, region: str, reason: str) -> None:
        self.calls.append((region, reason))


class _RecordingHealthy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, region: str) -> None:
        self.calls.append(region)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_heartbeat_records_liveness() -> None:
    clock = _Clock(_CLOCK_START)
    mon = HeartbeatMonitor(clock=clock)
    await mon.on_heartbeat(
        _hb_envelope("amygdala", uptime_s=_UPTIME_A, queue_depth=_QUEUE_DEPTH_A)
    )

    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.region == "amygdala"
    assert rec.last_heartbeat_ts == _CLOCK_START
    assert rec.last_status == "wake"
    assert rec.consecutive_misses == 0
    assert rec.queue_depth == _QUEUE_DEPTH_A
    assert rec.uptime_s == _UPTIME_A
    assert rec.build_sha == "abc1234"
    assert rec.dead is False


@pytest.mark.asyncio
async def test_heartbeat_resets_miss_count() -> None:
    clock = _Clock(_CLOCK_START)
    mon = HeartbeatMonitor(clock=clock)
    # Seed a stale record with misses already counted.
    mon._liveness["amygdala"] = RegionLiveness(
        region="amygdala",
        last_heartbeat_ts=0.0,
        last_status="wake",
        consecutive_misses=2,
    )
    clock.advance(_UPTIME_B)
    await mon.on_heartbeat(_hb_envelope("amygdala"))

    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.consecutive_misses == 0
    assert rec.last_heartbeat_ts == _CLOCK_AFTER_RESET


@pytest.mark.asyncio
async def test_sweep_increments_misses_when_stale() -> None:
    clock = _Clock(0.0)
    mon = HeartbeatMonitor(clock=clock)
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    clock.advance(DEFAULT_MISS_THRESHOLD_S + 1.0)

    await mon._sweep_once()
    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.consecutive_misses == 1
    assert rec.dead is False


@pytest.mark.asyncio
async def test_sweep_triggers_unhealthy_when_max_misses_exceeded() -> None:
    clock = _Clock(0.0)
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(clock=clock, on_unhealthy=on_unhealthy)
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    # Pre-seed misses so the next sweep pushes us past max_misses.
    rec = mon._liveness["amygdala"]
    rec.consecutive_misses = DEFAULT_MAX_MISSES
    clock.advance(DEFAULT_MISS_THRESHOLD_S + 1.0)

    await mon._sweep_once()
    assert on_unhealthy.calls == [("amygdala", "miss_threshold")]
    rec2 = mon.liveness("amygdala")
    assert rec2 is not None
    assert rec2.dead is True
    assert rec2.consecutive_misses == DEFAULT_MAX_MISSES + 1


@pytest.mark.asyncio
async def test_lwt_triggers_unhealthy_immediately() -> None:
    clock = _Clock(0.0)
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(clock=clock, on_unhealthy=on_unhealthy)
    env = _hb_envelope("amygdala", status="dead")
    await mon.on_heartbeat(env, retained=True)

    assert on_unhealthy.calls == [("amygdala", "lwt")]
    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.dead is True
    assert rec.last_status == "dead"


@pytest.mark.asyncio
async def test_non_retained_dead_status_does_not_fire_lwt_path() -> None:
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(on_unhealthy=on_unhealthy)
    env = _hb_envelope("amygdala", status="dead")
    await mon.on_heartbeat(env, retained=False)

    # Non-retained "dead" is a weird but not LWT signal — don't fire via the
    # LWT path. (Spec: regions never publish status="dead" directly.)
    assert on_unhealthy.calls == []
    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.dead is False


@pytest.mark.asyncio
async def test_resumed_heartbeat_fires_healthy() -> None:
    clock = _Clock(0.0)
    on_healthy = _RecordingHealthy()
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(
        clock=clock, on_unhealthy=on_unhealthy, on_healthy=on_healthy
    )
    await mon.on_heartbeat(_hb_envelope("amygdala", status="dead"), retained=True)
    assert on_unhealthy.calls == [("amygdala", "lwt")]

    clock.advance(1.0)
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    assert on_healthy.calls == ["amygdala"]
    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.dead is False
    assert rec.consecutive_misses == 0


@pytest.mark.asyncio
async def test_on_unhealthy_fires_only_once_per_death() -> None:
    clock = _Clock(0.0)
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(clock=clock, on_unhealthy=on_unhealthy)
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    mon._liveness["amygdala"].consecutive_misses = DEFAULT_MAX_MISSES
    clock.advance(DEFAULT_MISS_THRESHOLD_S + 1.0)

    await mon._sweep_once()
    clock.advance(DEFAULT_MISS_THRESHOLD_S + 1.0)
    await mon._sweep_once()
    clock.advance(DEFAULT_MISS_THRESHOLD_S + 1.0)
    await mon._sweep_once()

    assert on_unhealthy.calls == [("amygdala", "miss_threshold")]


@pytest.mark.asyncio
async def test_all_liveness_returns_copy() -> None:
    mon = HeartbeatMonitor()
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    snap = mon.all_liveness()
    snap.pop("amygdala", None)
    assert mon.liveness("amygdala") is not None


@pytest.mark.asyncio
async def test_liveness_none_for_unknown_region() -> None:
    mon = HeartbeatMonitor()
    assert mon.liveness("ghost") is None


@pytest.mark.asyncio
async def test_start_stop_idempotent() -> None:
    mon = HeartbeatMonitor(interval_s=0.05)
    await mon.start()
    await mon.start()  # second call no-op
    assert mon._task is not None and not mon._task.done()

    await mon.stop()
    await mon.stop()  # second stop no-op
    assert mon._task is None


@pytest.mark.asyncio
async def test_callbacks_receive_region_name() -> None:
    clock = _Clock(0.0)
    on_unhealthy = _RecordingUnhealthy()
    on_healthy = _RecordingHealthy()
    mon = HeartbeatMonitor(
        clock=clock, on_unhealthy=on_unhealthy, on_healthy=on_healthy
    )
    await mon.on_heartbeat(_hb_envelope("hippocampus", status="dead"), retained=True)
    await mon.on_heartbeat(_hb_envelope("hippocampus"))
    assert on_unhealthy.calls == [("hippocampus", "lwt")]
    assert on_healthy.calls == ["hippocampus"]


@pytest.mark.asyncio
async def test_clock_injected_deterministic_sweep() -> None:
    clock = _Clock(1000.0)
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(
        clock=clock,
        on_unhealthy=on_unhealthy,
        miss_threshold_s=10.0,
        max_misses=2,
    )
    await mon.on_heartbeat(_hb_envelope("r1"))

    # Under threshold: no miss.
    clock.advance(5.0)
    await mon._sweep_once()
    assert mon.liveness("r1").consecutive_misses == 0  # type: ignore[union-attr]

    # Over threshold each sweep: three sweeps → dead on the third.
    clock.advance(20.0)
    await mon._sweep_once()
    clock.advance(20.0)
    await mon._sweep_once()
    clock.advance(20.0)
    await mon._sweep_once()

    assert on_unhealthy.calls == [("r1", "miss_threshold")]
    assert mon.liveness("r1").dead is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_queue_depth_and_build_sha_updated() -> None:
    mon = HeartbeatMonitor()
    await mon.on_heartbeat(
        _hb_envelope(
            "amygdala",
            queue_depth=_QUEUE_DEPTH_B,
            uptime_s=_UPTIME_C,
            build_sha="deadbee",
        )
    )
    rec = mon.liveness("amygdala")
    assert rec is not None
    assert rec.queue_depth == _QUEUE_DEPTH_B
    assert rec.uptime_s == _UPTIME_C
    assert rec.build_sha == "deadbee"


@pytest.mark.asyncio
async def test_heartbeat_with_invalid_payload_does_not_crash() -> None:
    mon = HeartbeatMonitor()
    # Missing 'region' in data
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/system/heartbeat/amygdala",
        content_type="application/json",
        data={"status": "wake"},
    )
    # Must not raise.
    await mon.on_heartbeat(env)
    # No record was created because we couldn't identify the region.
    assert mon.all_liveness() == {}


@pytest.mark.asyncio
async def test_sweep_loop_runs_and_increments_misses() -> None:
    """Integration-lite: the real sweep loop increments misses over wall time."""
    clock = _Clock(0.0)
    on_unhealthy = _RecordingUnhealthy()
    mon = HeartbeatMonitor(
        clock=clock,
        on_unhealthy=on_unhealthy,
        interval_s=0.01,
        miss_threshold_s=0.0,  # any gap counts as a miss
        max_misses=1,
    )
    await mon.on_heartbeat(_hb_envelope("amygdala"))
    clock.advance(1.0)

    await mon.start()
    # Let the sweep loop run a few iterations.
    for _ in range(20):
        if on_unhealthy.calls:
            break
        await asyncio.sleep(0.02)
    await mon.stop()

    assert on_unhealthy.calls and on_unhealthy.calls[0][0] == "amygdala"


@pytest.mark.asyncio
async def test_non_heartbeat_content_type_ignored() -> None:
    """Envelopes whose data is not a dict don't crash the monitor."""
    mon = HeartbeatMonitor()
    env = Envelope.new(
        source_region="amygdala",
        topic="hive/system/heartbeat/amygdala",
        content_type="text/plain",
        data="not a dict",
    )
    await mon.on_heartbeat(env)
    assert mon.all_liveness() == {}
