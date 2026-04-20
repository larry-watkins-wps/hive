"""glia/metrics.py — System metrics aggregator (spec §E.9 + §H.2).

``MetricsAggregator`` aggregates per-region stats into three retained
system metrics topics, published on a configurable cadence (default 30s
per spec §E.9):

* ``hive/system/metrics/compute`` — CPU & memory pressure from docker stats.
* ``hive/system/metrics/tokens`` — aggregated from per-region region_stats.
* ``hive/system/metrics/region_health`` — derived from liveness map.

Three inputs:

1. :meth:`HeartbeatMonitor.all_liveness` → ``region_health``.
2. ``hive/system/region_stats/<region>`` envelopes (fed via
   :meth:`on_region_stats`) → ``tokens``.
3. Optional ``docker`` client → ``compute``. Best-effort; any docker error
   is logged and skipped (never kills the publish loop).

**Publish contract.** The ``publish`` callable is invoked as
``publish(envelope, retain=True)``. The supervisor's wrapper is
responsible for honouring the ``retain`` kwarg when sending to MQTT.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import structlog

from glia.heartbeat_monitor import HeartbeatMonitor
from glia.registry import RegionRegistry
from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Defaults & topics (spec §E.9)
# ---------------------------------------------------------------------------
DEFAULT_CADENCE_S = 30.0

TOPIC_METRICS_COMPUTE = "hive/system/metrics/compute"
TOPIC_METRICS_TOKENS = "hive/system/metrics/tokens"
TOPIC_METRICS_REGION_HEALTH = "hive/system/metrics/region_health"

_SOURCE_REGION = "glia"
_DEFAULT_CONTAINER_PREFIX = "hive-"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

RetainingPublish = Callable[..., Awaitable[None]]
"""Publish callable contract: ``publish(envelope, retain=True)``.

The supervisor's wrapper MUST honour the ``retain`` keyword by setting
the MQTT publish ``retain`` flag accordingly.
"""


@dataclass
class RegionStatsSnapshot:
    """Last-seen stats from ``hive/system/region_stats/<region>``."""

    region: str
    input_tokens_total: int = 0
    output_tokens_total: int = 0
    ts: str = ""


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class MetricsAggregator:
    """Aggregates per-region stats into retained system metrics topics.

    Construction does not start the publish loop — use :meth:`start` /
    :meth:`stop`. Callers feed region_stats envelopes via
    :meth:`on_region_stats`. The docker client is optional; if ``None``,
    the compute payload returns zeros.
    """

    def __init__(
        self,
        registry: RegionRegistry,
        heartbeat_monitor: HeartbeatMonitor,
        *,
        publish: RetainingPublish,
        docker_client: Any | None = None,
        cadence_s: float = DEFAULT_CADENCE_S,
        container_name_prefix: str = _DEFAULT_CONTAINER_PREFIX,
    ) -> None:
        self._registry = registry
        self._heartbeat = heartbeat_monitor
        self._publish = publish
        self._docker = docker_client
        self._cadence_s = cadence_s
        self._prefix = container_name_prefix
        self._stats: dict[str, RegionStatsSnapshot] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def on_region_stats(self, envelope: Envelope) -> None:
        """Update snapshot for a region from a region_stats envelope.

        Malformed envelopes (non-dict data, missing ``region``) are logged
        and skipped. Envelopes missing the ``llm`` sub-dict are skipped
        (logged at debug level) — the region is not added to the internal
        snapshot map. A region that never published with an ``llm`` field
        will not appear in the tokens payload.
        """
        data = envelope.payload.data
        if not isinstance(data, dict):
            log.warning(
                "metrics.invalid_region_stats",
                reason="data_not_dict",
                topic=envelope.topic,
            )
            return

        region = data.get("region") or envelope.source_region
        if not isinstance(region, str) or not region:
            log.warning(
                "metrics.invalid_region_stats",
                reason="missing_region",
                topic=envelope.topic,
            )
            return

        llm = data.get("llm")
        if not isinstance(llm, dict):
            log.debug(
                "metrics.region_stats_missing_llm",
                region=region,
                topic=envelope.topic,
            )
            return

        input_tokens = _coerce_int(llm.get("input_tokens_total", 0))
        output_tokens = _coerce_int(llm.get("output_tokens_total", 0))
        ts = data.get("ts", "")
        if not isinstance(ts, str):
            ts = str(ts)

        self._stats[region] = RegionStatsSnapshot(
            region=region,
            input_tokens_total=input_tokens,
            output_tokens_total=output_tokens,
            ts=ts,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the publish loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(
            self._publish_loop(), name="glia-metrics-publish"
        )

    async def stop(self) -> None:
        """Stop the publish loop. Idempotent and cancellation-safe."""
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
    # Aggregation helpers
    # ------------------------------------------------------------------

    def build_tokens_payload(self) -> dict[str, Any]:
        """Aggregate from ``self._stats`` snapshots."""
        per_region: dict[str, dict[str, int]] = {}
        total_in = 0
        total_out = 0
        for snap in self._stats.values():
            per_region[snap.region] = {
                "input_tokens": snap.input_tokens_total,
                "output_tokens": snap.output_tokens_total,
            }
            total_in += snap.input_tokens_total
            total_out += snap.output_tokens_total
        return {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "per_region": per_region,
        }

    def build_region_health_payload(self) -> dict[str, Any]:
        """Derive region_health payload from ``HeartbeatMonitor.all_liveness()``.

        Counting rules:
        - ``regions_up`` = not dead and ``consecutive_misses == 0``.
        - ``regions_degraded`` = not dead and ``consecutive_misses > 0``.
        - ``regions_down`` = ``dead`` is True.
        """
        liveness_map = self._heartbeat.all_liveness()
        regions_up = 0
        regions_degraded = 0
        regions_down = 0
        per_region: dict[str, dict[str, Any]] = {}

        for name, rec in liveness_map.items():
            if rec.dead:
                regions_down += 1
            elif rec.consecutive_misses > 0:
                regions_degraded += 1
            else:
                regions_up += 1

            per_region[name] = {
                "status": rec.last_status,
                "consecutive_misses": rec.consecutive_misses,
                "uptime_s": rec.uptime_s,
            }

        if regions_down > 0:
            summary = "down"
        elif regions_degraded > 0:
            summary = "degraded"
        else:
            summary = "healthy"

        return {
            "summary": summary,
            "regions_up": regions_up,
            "regions_degraded": regions_degraded,
            "regions_down": regions_down,
            "per_region": per_region,
        }

    def build_compute_payload(self) -> dict[str, Any]:
        """Query docker stats for active regions and aggregate.

        If ``docker_client`` is ``None``, return zeros and empty
        ``per_region``. Any docker exception is caught, logged, and the
        region is skipped.
        """
        if self._docker is None:
            return {"total_cpu_pct": 0, "total_mem_mb": 0, "per_region": {}}

        per_region: dict[str, dict[str, float]] = {}
        total_cpu = 0.0
        total_mem = 0.0

        for entry in self._registry.active():
            container_name = f"{self._prefix}{entry.name}"
            try:
                container = self._docker.containers.get(container_name)
                stats = container.stats(stream=False)
            except Exception as exc:  # docker NotFound, APIError, etc.
                log.debug(
                    "metrics.docker_stats_skipped",
                    region=entry.name,
                    container=container_name,
                    error=type(exc).__name__,
                )
                continue

            cpu_pct = _compute_cpu_pct(stats)
            mem_mb = _compute_mem_mb(stats)
            per_region[entry.name] = {"cpu_pct": cpu_pct, "mem_mb": mem_mb}
            total_cpu += cpu_pct
            total_mem += mem_mb

        return {
            "total_cpu_pct": round(total_cpu, 2),
            "total_mem_mb": round(total_mem, 2),
            "per_region": per_region,
        }

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_once(self) -> None:
        """Publish all three retained metrics topics once."""
        await self._emit(TOPIC_METRICS_COMPUTE, self.build_compute_payload())
        await self._emit(TOPIC_METRICS_TOKENS, self.build_tokens_payload())
        await self._emit(
            TOPIC_METRICS_REGION_HEALTH, self.build_region_health_payload()
        )

    async def _emit(self, topic: str, data: dict[str, Any]) -> None:
        envelope = Envelope.new(
            source_region=_SOURCE_REGION,
            topic=topic,
            content_type="application/json",
            data=data,
        )
        try:
            await self._publish(envelope, retain=True)
        except Exception:
            log.exception("metrics.publish_failed", topic=topic)

    async def _publish_loop(self) -> None:
        while not self._stopping:
            try:
                await self.publish_once()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("metrics.publish_once_failed")
            try:
                await asyncio.sleep(self._cadence_s)
            except asyncio.CancelledError:
                break


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _coerce_int(v: Any) -> int:
    if isinstance(v, bool):  # bool is int subclass — reject explicitly
        return 0
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _compute_cpu_pct(stats: dict[str, Any]) -> float:
    """Docker-style CPU% calculation. Returns 0.0 on missing fields."""
    try:
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        num_cpus = stats["cpu_stats"]["online_cpus"]
    except (KeyError, TypeError):
        return 0.0

    if system_delta > 0 and cpu_delta >= 0 and num_cpus:
        return round((cpu_delta / system_delta) * num_cpus * 100.0, 2)
    return 0.0


def _compute_mem_mb(stats: dict[str, Any]) -> float:
    """Container memory in MiB, with page cache subtracted.

    Docker's ``memory_stats.usage`` includes the page cache, which overstates
    actual memory pressure. cgroups v2 exposes ``inactive_file``; v1 exposes
    ``cache``. We prefer v2 and fall back to v1. Returns 0.0 on missing fields.
    """
    try:
        usage = stats["memory_stats"]["usage"]
        sub_stats = stats["memory_stats"].get("stats", {}) or {}
        # cgroups v2 exposes inactive_file; v1 exposes cache. Prefer v2.
        cache = sub_stats.get("inactive_file", sub_stats.get("cache", 0))
        return round(max(usage - cache, 0) / (1024 * 1024), 2)
    except (KeyError, TypeError):
        return 0.0
