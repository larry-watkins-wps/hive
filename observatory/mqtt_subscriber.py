"""Subscribes hive/# and fans each envelope out to observatory components."""
from __future__ import annotations

import asyncio
import json
import re
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

    Supports two shapes so the observatory stays useful regardless of which
    schema a region file uses:

    1. Flat list (simple, used by unit tests + sidecar/standalone demos)::

            topics:
              - hive/foo/#
              - hive/bar

    2. Rich-record list (production Hive schema with qos / description
       metadata per subscription)::

            schema_version: 1
            subscriptions:
              - topic: hive/foo/#
                qos: 1
                description: ...

    Malformed YAML in one region is logged and skipped — one bad file must
    not poison the observatory for the rest of the tree. Non-string / non-
    dict items are filtered out. Missing files are skipped silently.
    """
    out: dict[str, list[str]] = {}
    regions_dir = hive_repo_root / "regions"
    if not regions_dir.exists():
        return out
    for region_dir in sorted(p for p in regions_dir.iterdir() if p.is_dir()):
        sub_file = region_dir / "subscriptions.yaml"
        if not sub_file.exists():
            continue
        try:
            data = _YAML.load(sub_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — never let one region's typo kill startup
            log.exception("observatory.bad_subscriptions_yaml", path=str(sub_file))
            continue
        if not isinstance(data, dict):
            log.debug("observatory.subscriptions_non_mapping", path=str(sub_file))
            continue
        topics = _extract_topics(data, path=sub_file)
        if topics:
            out[region_dir.name] = topics
    return out


def _extract_topics(data: dict, *, path: Path) -> list[str]:
    """Pull the subscription topic list out of either schema shape.

    Prefers `subscriptions:` (Hive production shape, list of dicts with a
    `topic` key) because real region files all use it; falls back to a
    flat `topics:` list when present. A region file that contains both
    keys is extremely unlikely in practice, but if it happens we union
    the two and dedupe while preserving order so no subscription is lost.
    """
    topics: list[str] = []
    seen: set[str] = set()

    def _push(t: object) -> None:
        if isinstance(t, str) and t not in seen:
            seen.add(t)
            topics.append(t)

    subs_raw = data.get("subscriptions")
    if isinstance(subs_raw, list):
        for item in subs_raw:
            if isinstance(item, dict):
                _push(item.get("topic"))
            elif isinstance(item, str):
                _push(item)
    elif subs_raw is not None:
        log.debug("observatory.subscriptions_field_non_list", path=str(path))

    topics_raw = data.get("topics")
    if isinstance(topics_raw, list):
        for item in topics_raw:
            _push(item)
    elif topics_raw is not None:
        log.debug("observatory.subscriptions_topics_non_list", path=str(path))

    return topics


def _mqtt_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile an MQTT topic filter to a regex.

    MQTT wildcards (single-level `+`, multi-level `#` at end only) are
    *not* fnmatch semantics — `+` must match exactly one topic segment
    (no ``/``) and `#` must match one or more full segments at the end
    of the filter. ``fnmatch`` treats ``*`` as "any chars including
    ``/``" which over-matches (e.g. ``hive/+/plan`` would incorrectly
    match ``hive/a/b/plan``). So we go direct to a regex.
    """
    parts: list[str] = []
    segments = pattern.split("/")
    for i, seg in enumerate(segments):
        is_last = i == len(segments) - 1
        if seg == "#":
            if not is_last:
                # Malformed filter (# only valid at end). Translate to match
                # nothing — caller's higher-level validation is out of scope.
                parts.append(r"$.^")  # never matches
                break
            # `hive/#` should match `hive/a`, `hive/a/b`, ...; `#` alone
            # matches any non-empty topic. Add an optional leading `/`
            # consumed already by the join above — so just `.+`.
            parts.append(r".+")
            break
        if seg == "+":
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile(r"\A" + r"/".join(parts) + r"\Z")


_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _matches(topic: str, pattern: str) -> bool:
    """MQTT-correct topic-filter match. Compiled patterns are cached."""
    rx = _PATTERN_CACHE.get(pattern)
    if rx is None:
        rx = _mqtt_pattern_to_regex(pattern)
        _PATTERN_CACHE[pattern] = rx
    return rx.match(topic) is not None


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
        # Monotonic counter incremented on every message that survives
        # JSON parsing. Consumed by the watchdog in ``service.py`` to detect
        # silent MQTT stalls — aiomqtt's async iterator can wait forever
        # when paho's `loop_read` degrades without firing `on_disconnect`
        # (observed on aiomqtt 2.5.1), and the supervising loop has no
        # signal to reconnect with. A stagnant counter = force-reconnect.
        self.messages_received_total = 0

    def _inferred_destinations(self, topic: str, source: str | None) -> tuple[str, ...]:
        if source is None:
            # No source → no trustworthy destination inference. Record an
            # empty tuple; the envelope still lands in the ring for display.
            return ()
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
        if source is None:
            log.debug("observatory.envelope_missing_source", topic=topic)
        destinations = self._inferred_destinations(topic, source)

        # Retained state (modulators, self, interoception, attention, metrics).
        if any(topic.startswith(p) for p in _RETAINED_PREFIXES) or getattr(msg, "retain", False):
            self.cache.put(topic, envelope)

        # Heartbeats update the registry in place.
        if topic.startswith(_HEARTBEAT_PREFIX):
            region_name = topic[len(_HEARTBEAT_PREFIX):]
            heartbeat = self._extract_heartbeat_stats(envelope.get("payload"), topic=topic)
            if heartbeat is not None:
                self.registry.apply_heartbeat(region_name, heartbeat)

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

        # Increment at the end so malformed payloads (non-JSON / non-dict)
        # don't count as "we are receiving traffic" — the watchdog needs a
        # signal that the decode path is healthy, not just that bytes arrived.
        self.messages_received_total += 1

    @staticmethod
    def _extract_heartbeat_stats(payload: Any, *, topic: str) -> dict[str, Any] | None:
        """Return the heartbeat-stats dict from either the flat plan shape
        (``payload`` IS the stats dict) or the production shape (stats live
        under ``payload.data``). Anything else is skipped with a debug log.
        """
        if not isinstance(payload, dict):
            log.debug("observatory.skip_heartbeat_non_dict_payload", topic=topic)
            return None
        if isinstance(payload.get("data"), dict):
            return payload["data"]
        if "data" in payload:
            # Wrapped shape with non-dict `data` — no heartbeat stats here.
            log.debug("observatory.skip_heartbeat_wrapped_non_dict_data", topic=topic)
            return None
        # Flat shape: the payload IS the stats dict (plan format).
        return payload

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
                log.exception(
                    "observatory.dispatch_failed",
                    topic=str(message.topic),
                    bytes=len(getattr(message, "payload", b"")),
                )
