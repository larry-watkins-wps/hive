"""Subscribes hive/# and fans each envelope out to observatory components."""
from __future__ import annotations

import asyncio
import fnmatch
import json
import time
from pathlib import Path
from typing import Any

import structlog
from ruamel.yaml import YAML

from observatory.adjacency import Adjacency
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord

_YAML = YAML(typ="safe")
log = structlog.get_logger(__name__)

_RETAINED_PREFIXES = (
    "hive/modulator/",
    "hive/self/",
    "hive/interoception/",
    "hive/attention/",
    "hive/system/metrics/",
)
_HEARTBEAT_PREFIX = "hive/system/heartbeat/"


def load_subscription_map(hive_repo_root: Path) -> dict[str, list[str]]:
    """Scan regions/<name>/subscriptions.yaml and return {region: [topic, ...]}.

    Missing files are skipped silently — regions may not have landed yet. This
    is read once at startup; dynamic sub changes are out of scope for v1.
    """
    out: dict[str, list[str]] = {}
    regions_dir = hive_repo_root / "regions"
    if not regions_dir.exists():
        return out
    for region_dir in sorted(p for p in regions_dir.iterdir() if p.is_dir()):
        sub_file = region_dir / "subscriptions.yaml"
        if not sub_file.exists():
            continue
        data = _YAML.load(sub_file.read_text(encoding="utf-8")) or {}
        topics = data.get("topics") or []
        if topics:
            out[region_dir.name] = list(topics)
    return out


def _matches(topic: str, pattern: str) -> bool:
    # MQTT wildcards: + single level, # multi level. Convert to fnmatch.
    return fnmatch.fnmatchcase(
        topic, pattern.replace("+", "*").replace("/#", "/*").replace("#", "*")
    )


class MqttSubscriber:
    def __init__(
        self,
        ring: RingBuffer,
        cache: RetainedCache,
        registry: RegionRegistry,
        adjacency: Adjacency,
        subscription_map: dict[str, list[str]],
    ) -> None:
        self.ring = ring
        self.cache = cache
        self.registry = registry
        self.adjacency = adjacency
        self._sub_map = subscription_map

    def _inferred_destinations(self, topic: str, source: str | None) -> tuple[str, ...]:
        dests: list[str] = []
        for region, patterns in self._sub_map.items():
            if region == source:
                continue
            if any(_matches(topic, p) for p in patterns):
                dests.append(region)
        return tuple(dests)

    async def dispatch(self, msg: Any) -> None:
        topic = msg.topic.value if hasattr(msg.topic, "value") else str(msg.topic)

        # Parse envelope; non-JSON payloads (e.g., raw hardware bytes) are skipped.
        try:
            envelope = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.debug("observatory.skip_non_json", topic=topic, bytes=len(msg.payload))
            return
        if not isinstance(envelope, dict):
            log.debug("observatory.skip_non_dict_envelope", topic=topic)
            return

        source = envelope.get("source_region")
        destinations = self._inferred_destinations(topic, source)

        # Retained state (modulators, self, interoception, attention, metrics).
        if any(topic.startswith(p) for p in _RETAINED_PREFIXES) or getattr(msg, "retain", False):
            self.cache.put(topic, envelope)

        # Heartbeats update the registry in place.
        if topic.startswith(_HEARTBEAT_PREFIX):
            region_name = topic[len(_HEARTBEAT_PREFIX):]
            payload = envelope.get("payload", {})
            # Real envelopes wrap heartbeat stats under payload.data per
            # shared/message_envelope.py; the plan's test fixtures pass them
            # flat. Accept both shapes.
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                payload = payload["data"]
            if isinstance(payload, dict):
                self.registry.apply_heartbeat(region_name, payload)

        # Record in ring + adjacency for traffic viz.
        now = time.monotonic()
        self.ring.append(
            RingRecord(
                observed_at=now,
                topic=topic,
                envelope=envelope,
                source_region=source,
                destinations=destinations,
            )
        )
        if source and destinations:
            self.adjacency.record(source, list(destinations), now=now)

    async def run(self, client: Any, stop_event: asyncio.Event) -> None:
        """Main loop — consume messages until ``stop_event`` fires.

        ``client`` is an already-connected ``aiomqtt.Client`` with an active
        ``hive/#`` subscription.
        """
        async for message in client.messages:
            if stop_event.is_set():
                break
            try:
                await self.dispatch(message)
            except Exception:  # noqa: BLE001 — don't kill the subscriber on one bad message
                log.exception("observatory.dispatch_failed", topic=str(message.topic))
