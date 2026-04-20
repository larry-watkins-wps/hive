"""Tests for glia.metrics — spec §E.9 + §H.2.

MetricsAggregator subscribes to region_stats envelopes and heartbeat liveness
map, then publishes three retained system metrics topics on a cadence:
- hive/system/metrics/compute
- hive/system/metrics/tokens
- hive/system/metrics/region_health
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from docker.errors import NotFound  # type: ignore[import-untyped]

from glia.heartbeat_monitor import HeartbeatMonitor, RegionLiveness
from glia.metrics import (
    DEFAULT_CADENCE_S,
    TOPIC_METRICS_COMPUTE,
    TOPIC_METRICS_REGION_HEALTH,
    TOPIC_METRICS_TOKENS,
    MetricsAggregator,
)
from glia.registry import RegionRegistry
from shared.message_envelope import Envelope

# ---------------------------------------------------------------------------
# Test constants (avoid PLR2004 magic-value comparisons)
# ---------------------------------------------------------------------------
_INPUT_TOKENS_A = 12345
_OUTPUT_TOKENS_A = 6789
_INPUT_TOKENS_B = 1000
_OUTPUT_TOKENS_B = 500
_INPUT_TOKENS_C = 50
_OUTPUT_TOKENS_C = 25

_LATEST_IN = 100
_LATEST_OUT = 50
_PREV_IN = 10
_PREV_OUT = 5

_FIRST_IN = 111
_FIRST_OUT = 22

_NUM_REGIONS = 14
_TEST_UPTIME_S = 100

_FAST_CADENCE_S = 0.01
_LOOP_RUN_S = 0.05
_MIN_PUBLISHES = 3  # one full cycle
_PUBLISHES_PER_CYCLE = 3
_DEFAULT_CADENCE = 30.0
_SLOW_PUBLISH_WAIT_S = 10.0
_MIXED_UP_COUNT = 2
_RETAIN_POSITIONAL_ARG_COUNT = 2

_MEM_MB = 10.0
_CPU_PCT_PER_CONTAINER = 20.0
_CPU_DELTA_NUM = 1_000_000
_CPU_TOTAL_CURR = 2_000_000
_CPU_TOTAL_PREV = 1_000_000
_SYS_TOTAL_CURR = 20_000_000
_SYS_TOTAL_PREV = 10_000_000
_NUM_CPUS = 2
_MEM_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stats_envelope(
    region: str = "prefrontal_cortex",
    *,
    input_tokens_total: int = _INPUT_TOKENS_A,
    output_tokens_total: int = _OUTPUT_TOKENS_A,
    omit_llm: bool = False,
    bad_data: bool = False,
) -> Envelope:
    data: Any
    if bad_data:
        data = "not-a-dict"
    elif omit_llm:
        data = {"region": region, "uptime_s": 10}
    else:
        data = {
            "region": region,
            "ts": "2026-04-19T10:30:00.000Z",
            "uptime_s": 1234,
            "phase": "wake",
            "build_sha": "abc1234",
            "handlers": {"count": 5, "degraded": 0},
            "mqtt": {
                "messages_in_total": 1,
                "messages_out_total": 1,
                "subscribed_topics": 1,
                "reconnects": 0,
            },
            "llm": {
                "calls_total": 10,
                "cache_hits_total": 3,
                "input_tokens_total": input_tokens_total,
                "output_tokens_total": output_tokens_total,
                "errors_total": 0,
                "over_budget_events": 0,
            },
            "memory": {"stm_bytes": 100, "ltm_files": 1, "index_terms": 10},
            "sleep": {
                "cycles_total": 0,
                "last_sleep_ts": "2026-04-19T09:00:00.000Z",
                "last_commit_sha": None,
            },
        }
    return Envelope.new(
        source_region=region,
        topic=f"hive/system/region_stats/{region}",
        content_type="application/json",
        data=data,
    )


def _make_liveness(
    region: str,
    *,
    consecutive_misses: int = 0,
    dead: bool = False,
    uptime_s: int = _TEST_UPTIME_S,
    status: str = "wake",
) -> RegionLiveness:
    return RegionLiveness(
        region=region,
        last_heartbeat_ts=0.0,
        last_status=status,
        consecutive_misses=consecutive_misses,
        queue_depth=0,
        uptime_s=uptime_s,
        build_sha="abc1234",
        dead=dead,
    )


def _fake_docker_stats(
    *,
    cpu_total: int = _CPU_TOTAL_CURR,
    pre_cpu_total: int = _CPU_TOTAL_PREV,
    system_total: int = _SYS_TOTAL_CURR,
    pre_system_total: int = _SYS_TOTAL_PREV,
    num_cpus: int = _NUM_CPUS,
    mem_usage_bytes: int = _MEM_BYTES,
) -> dict[str, Any]:
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total},
            "system_cpu_usage": system_total,
            "online_cpus": num_cpus,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": pre_cpu_total},
            "system_cpu_usage": pre_system_total,
        },
        "memory_stats": {"usage": mem_usage_bytes},
    }


def _inject_liveness(
    monitor: HeartbeatMonitor, records: list[RegionLiveness]
) -> None:
    for rec in records:
        monitor._liveness[rec.region] = rec  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> RegionRegistry:
    return RegionRegistry.load()


@pytest.fixture
def heartbeat_monitor() -> HeartbeatMonitor:
    return HeartbeatMonitor(interval_s=0.1, miss_threshold_s=10, max_misses=3)


@pytest.fixture
def publish() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def aggregator(
    registry: RegionRegistry,
    heartbeat_monitor: HeartbeatMonitor,
    publish: AsyncMock,
) -> MetricsAggregator:
    return MetricsAggregator(
        registry,
        heartbeat_monitor,
        publish=publish,
        docker_client=None,
        cadence_s=_FAST_CADENCE_S,
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


async def test_on_region_stats_updates_snapshot(aggregator: MetricsAggregator) -> None:
    env = _stats_envelope(
        "prefrontal_cortex",
        input_tokens_total=_FIRST_IN,
        output_tokens_total=_FIRST_OUT,
    )
    await aggregator.on_region_stats(env)

    payload = aggregator.build_tokens_payload()
    assert payload["per_region"]["prefrontal_cortex"] == {
        "input_tokens": _FIRST_IN,
        "output_tokens": _FIRST_OUT,
    }


async def test_on_region_stats_latest_wins(aggregator: MetricsAggregator) -> None:
    await aggregator.on_region_stats(
        _stats_envelope(
            "amygdala",
            input_tokens_total=_PREV_IN,
            output_tokens_total=_PREV_OUT,
        )
    )
    await aggregator.on_region_stats(
        _stats_envelope(
            "amygdala",
            input_tokens_total=_LATEST_IN,
            output_tokens_total=_LATEST_OUT,
        )
    )
    payload = aggregator.build_tokens_payload()
    assert payload["per_region"]["amygdala"] == {
        "input_tokens": _LATEST_IN,
        "output_tokens": _LATEST_OUT,
    }
    assert payload["total_input_tokens"] == _LATEST_IN
    assert payload["total_output_tokens"] == _LATEST_OUT


async def test_on_region_stats_ignores_malformed_non_dict(
    aggregator: MetricsAggregator,
) -> None:
    env = _stats_envelope("thalamus", bad_data=True)
    # Should not raise.
    await aggregator.on_region_stats(env)
    assert aggregator.build_tokens_payload()["per_region"] == {}


async def test_on_region_stats_ignores_missing_llm(
    aggregator: MetricsAggregator,
) -> None:
    env = _stats_envelope("thalamus", omit_llm=True)
    # Must not crash; region should not appear (no llm sub-dict).
    await aggregator.on_region_stats(env)
    payload = aggregator.build_tokens_payload()
    assert "thalamus" not in payload["per_region"]


# ---------------------------------------------------------------------------
# Tokens aggregation
# ---------------------------------------------------------------------------


async def test_build_tokens_payload_sums_and_groups(
    aggregator: MetricsAggregator,
) -> None:
    await aggregator.on_region_stats(
        _stats_envelope(
            "prefrontal_cortex",
            input_tokens_total=_INPUT_TOKENS_A,
            output_tokens_total=_OUTPUT_TOKENS_A,
        )
    )
    await aggregator.on_region_stats(
        _stats_envelope(
            "amygdala",
            input_tokens_total=_INPUT_TOKENS_B,
            output_tokens_total=_OUTPUT_TOKENS_B,
        )
    )
    await aggregator.on_region_stats(
        _stats_envelope(
            "thalamus",
            input_tokens_total=_INPUT_TOKENS_C,
            output_tokens_total=_OUTPUT_TOKENS_C,
        )
    )
    payload = aggregator.build_tokens_payload()
    expected_in = _INPUT_TOKENS_A + _INPUT_TOKENS_B + _INPUT_TOKENS_C
    expected_out = _OUTPUT_TOKENS_A + _OUTPUT_TOKENS_B + _OUTPUT_TOKENS_C
    assert payload["total_input_tokens"] == expected_in
    assert payload["total_output_tokens"] == expected_out
    assert set(payload["per_region"].keys()) == {
        "prefrontal_cortex",
        "amygdala",
        "thalamus",
    }
    assert payload["per_region"]["prefrontal_cortex"]["input_tokens"] == _INPUT_TOKENS_A


# ---------------------------------------------------------------------------
# Region health
# ---------------------------------------------------------------------------


def test_build_region_health_all_up(
    aggregator: MetricsAggregator, heartbeat_monitor: HeartbeatMonitor
) -> None:
    regions = [
        _make_liveness(f"region_{i}", consecutive_misses=0, dead=False)
        for i in range(_NUM_REGIONS)
    ]
    _inject_liveness(heartbeat_monitor, regions)

    payload = aggregator.build_region_health_payload()
    assert payload["summary"] == "healthy"
    assert payload["regions_up"] == _NUM_REGIONS
    assert payload["regions_degraded"] == 0
    assert payload["regions_down"] == 0
    assert len(payload["per_region"]) == _NUM_REGIONS
    sample = payload["per_region"]["region_0"]
    assert sample == {
        "status": "wake",
        "consecutive_misses": 0,
        "uptime_s": _TEST_UPTIME_S,
    }


def test_build_region_health_degraded(
    aggregator: MetricsAggregator, heartbeat_monitor: HeartbeatMonitor
) -> None:
    _inject_liveness(
        heartbeat_monitor,
        [
            _make_liveness("a", consecutive_misses=0, dead=False),
            _make_liveness("b", consecutive_misses=1, dead=False),
        ],
    )
    payload = aggregator.build_region_health_payload()
    assert payload["summary"] == "degraded"
    assert payload["regions_up"] == 1
    assert payload["regions_degraded"] == 1
    assert payload["regions_down"] == 0


def test_build_region_health_dead(
    aggregator: MetricsAggregator, heartbeat_monitor: HeartbeatMonitor
) -> None:
    _inject_liveness(
        heartbeat_monitor,
        [
            _make_liveness("a", dead=False),
            _make_liveness("b", dead=True),
        ],
    )
    payload = aggregator.build_region_health_payload()
    assert payload["summary"] == "down"
    assert payload["regions_down"] == 1


def test_build_region_health_mixed(
    aggregator: MetricsAggregator, heartbeat_monitor: HeartbeatMonitor
) -> None:
    _inject_liveness(
        heartbeat_monitor,
        [
            _make_liveness("a", consecutive_misses=0, dead=False),
            _make_liveness("b", consecutive_misses=2, dead=False),
            _make_liveness("c", consecutive_misses=0, dead=False),
            _make_liveness("d", dead=True),
        ],
    )
    payload = aggregator.build_region_health_payload()
    assert payload["summary"] == "down"
    assert payload["regions_up"] == _MIXED_UP_COUNT
    assert payload["regions_degraded"] == 1
    assert payload["regions_down"] == 1


# ---------------------------------------------------------------------------
# Compute payload
# ---------------------------------------------------------------------------


def test_build_compute_payload_no_docker(aggregator: MetricsAggregator) -> None:
    payload = aggregator.build_compute_payload()
    assert payload == {"total_cpu_pct": 0, "total_mem_mb": 0, "per_region": {}}


def test_build_compute_payload_sums_containers(
    registry: RegionRegistry,
    heartbeat_monitor: HeartbeatMonitor,
    publish: AsyncMock,
) -> None:
    docker_client = MagicMock()

    def _container_get(_name: str) -> MagicMock:
        container = MagicMock()
        container.stats.return_value = _fake_docker_stats()
        return container

    docker_client.containers.get.side_effect = _container_get

    aggregator = MetricsAggregator(
        registry,
        heartbeat_monitor,
        publish=publish,
        docker_client=docker_client,
        cadence_s=_FAST_CADENCE_S,
    )

    payload = aggregator.build_compute_payload()
    active_count = len(registry.active())
    assert len(payload["per_region"]) == active_count
    assert payload["total_cpu_pct"] == pytest.approx(
        _CPU_PCT_PER_CONTAINER * active_count
    )
    assert payload["total_mem_mb"] == pytest.approx(_MEM_MB * active_count)
    # Verify container name prefix
    docker_client.containers.get.assert_any_call(
        f"hive-{registry.active()[0].name}"
    )


def test_build_compute_payload_missing_container_skipped(
    registry: RegionRegistry,
    heartbeat_monitor: HeartbeatMonitor,
    publish: AsyncMock,
) -> None:
    docker_client = MagicMock()
    active = registry.active()
    missing_name = active[0].name
    present_names = {e.name for e in active[1:]}

    def _container_get(name: str) -> MagicMock:
        if name == f"hive-{missing_name}":
            raise NotFound(f"no such container {name}")
        container = MagicMock()
        container.stats.return_value = _fake_docker_stats()
        return container

    docker_client.containers.get.side_effect = _container_get

    aggregator = MetricsAggregator(
        registry,
        heartbeat_monitor,
        publish=publish,
        docker_client=docker_client,
    )

    payload = aggregator.build_compute_payload()
    assert missing_name not in payload["per_region"]
    for n in present_names:
        assert n in payload["per_region"]


def test_build_compute_payload_missing_stats_fields_zero(
    registry: RegionRegistry,
    heartbeat_monitor: HeartbeatMonitor,
    publish: AsyncMock,
) -> None:
    docker_client = MagicMock()
    container = MagicMock()
    container.stats.return_value = {
        "cpu_stats": {},
        "precpu_stats": {},
        "memory_stats": {},
    }
    docker_client.containers.get.return_value = container

    aggregator = MetricsAggregator(
        registry,
        heartbeat_monitor,
        publish=publish,
        docker_client=docker_client,
    )
    payload = aggregator.build_compute_payload()
    assert payload["total_cpu_pct"] == 0
    assert payload["total_mem_mb"] == 0
    # per_region entries still present (0/0).
    assert len(payload["per_region"]) == len(registry.active())


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def test_publish_once_publishes_three_topics(
    aggregator: MetricsAggregator, publish: AsyncMock
) -> None:
    await aggregator.publish_once()
    assert publish.await_count == _PUBLISHES_PER_CYCLE
    topics = {call.args[0].topic for call in publish.await_args_list}
    assert topics == {
        TOPIC_METRICS_COMPUTE,
        TOPIC_METRICS_TOKENS,
        TOPIC_METRICS_REGION_HEALTH,
    }


async def test_publish_once_retain_true(
    aggregator: MetricsAggregator, publish: AsyncMock
) -> None:
    await aggregator.publish_once()
    for call in publish.await_args_list:
        retain = call.kwargs.get("retain")
        if retain is None and len(call.args) >= _RETAIN_POSITIONAL_ARG_COUNT:
            retain = call.args[1]
        assert retain is True, f"expected retain=True for call {call}"


async def test_publish_once_envelope_source_region_is_glia(
    aggregator: MetricsAggregator, publish: AsyncMock
) -> None:
    await aggregator.publish_once()
    for call in publish.await_args_list:
        env = call.args[0]
        assert env.source_region == "glia"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_start_stop_idempotent(aggregator: MetricsAggregator) -> None:
    await aggregator.start()
    await aggregator.start()  # no raise
    await aggregator.stop()
    await aggregator.stop()  # no raise


async def test_publish_loop_respects_cadence(
    aggregator: MetricsAggregator, publish: AsyncMock
) -> None:
    await aggregator.start()
    try:
        await asyncio.sleep(_LOOP_RUN_S)
    finally:
        await aggregator.stop()
    # At cadence_s=0.01 and 0.05s elapsed we expect ~5 cycles, each 3 publishes.
    # Allow a generous lower bound to avoid flakiness: at least one full cycle.
    assert publish.await_count >= _MIN_PUBLISHES


async def test_stop_cancels_inflight_publish(
    registry: RegionRegistry,
    heartbeat_monitor: HeartbeatMonitor,
) -> None:
    slow_publish = AsyncMock()

    async def _slow(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.sleep(_SLOW_PUBLISH_WAIT_S)

    slow_publish.side_effect = _slow
    agg = MetricsAggregator(
        registry,
        heartbeat_monitor,
        publish=slow_publish,
        docker_client=None,
        cadence_s=_FAST_CADENCE_S,
    )
    await agg.start()
    # Yield so the task enters publish_once.
    await asyncio.sleep(0)
    await agg.stop()
    # No hang, no raise. Task should be cleared.


def test_default_cadence_is_30s() -> None:
    assert DEFAULT_CADENCE_S == _DEFAULT_CADENCE
