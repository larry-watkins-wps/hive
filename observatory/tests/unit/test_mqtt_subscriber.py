from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from observatory.adjacency import Adjacency
from observatory.mqtt_subscriber import MqttSubscriber
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer


@dataclass
class FakeMsg:
    topic: str
    payload: bytes
    retain: bool = False

    # aiomqtt's Message has a .topic.value attr — emulate it
    class _T(str):
        @property
        def value(self) -> str:  # type: ignore[override]
            return str(self)

    def __post_init__(self) -> None:
        self.topic = FakeMsg._T(self.topic)  # type: ignore[assignment]


def _envelope(topic: str, source: str, payload: dict) -> bytes:
    return json.dumps({
        "id": "x",
        "timestamp": "2026-04-20T00:00:00.000Z",
        "source_region": source,
        "topic": topic,
        "payload": payload,
    }).encode()


@pytest.mark.asyncio
async def test_dispatches_envelope_to_ring_buffer() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/cognitive/prefrontal/plan",
        payload=_envelope("hive/cognitive/prefrontal/plan", "thalamus", {"x": 1}),
    )
    await sub.dispatch(msg)

    [rec] = ring.snapshot()
    assert rec.topic == "hive/cognitive/prefrontal/plan"
    assert rec.source_region == "thalamus"


@pytest.mark.asyncio
async def test_heartbeat_updates_registry_without_filling_ring() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/system/heartbeat/thalamus",
        payload=_envelope(
            "hive/system/heartbeat/thalamus",
            "thalamus",
            {"phase": "wake", "queue_depth_messages": 2, "stm_bytes": 0,
             "llm_tokens_used_lifetime": 0, "handler_count": 1, "last_error_ts": None},
        ),
    )
    await sub.dispatch(msg)
    assert reg.get("thalamus").stats.phase == "wake"
    assert len(ring) == 1  # heartbeats still recorded (for traffic viz); not suppressed


@pytest.mark.asyncio
async def test_heartbeat_accepts_wrapped_payload_shape() -> None:
    """Production envelopes wrap payload as {content_type, data, encoding} per
    shared/message_envelope.py. The heartbeat branch must unwrap payload.data
    in addition to the plan's flat shape. See decisions.md 2026-04-20 entry.
    """
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    wrapped_payload = {
        "content_type": "application/hive+self-state",
        "encoding": "utf-8",
        "data": {
            "phase": "sleep",
            "queue_depth_messages": 7,
            "stm_bytes": 1024,
            "llm_tokens_used_lifetime": 42,
            "handler_count": 3,
            "last_error_ts": None,
        },
    }
    msg = FakeMsg(
        topic="hive/system/heartbeat/amygdala",
        payload=_envelope("hive/system/heartbeat/amygdala", "amygdala", wrapped_payload),
    )
    await sub.dispatch(msg)

    stats = reg.get("amygdala").stats
    assert stats.phase == "sleep"
    assert stats.queue_depth == 7  # noqa: PLR2004
    assert stats.stm_bytes == 1024  # noqa: PLR2004
    assert stats.tokens_lifetime == 42  # noqa: PLR2004
    assert stats.handler_count == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_retained_modulator_goes_into_cache() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/modulator/cortisol",
        payload=_envelope("hive/modulator/cortisol", "amygdala", {"value": 0.6}),
        retain=True,
    )
    await sub.dispatch(msg)
    got = cache.get("hive/modulator/cortisol")
    assert got is not None
    assert got["payload"]["value"] == 0.6  # noqa: PLR2004


@pytest.mark.asyncio
async def test_destinations_inferred_from_subscription_map() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    # thalamus subscribes to cognitive/prefrontal/plan → when prefrontal publishes it,
    # no one's "source" on the cognitive side is prefrontal; but destinations
    # should include thalamus.
    sub_map = {"thalamus": ["hive/cognitive/prefrontal/plan"]}
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map=sub_map)

    msg = FakeMsg(
        topic="hive/cognitive/prefrontal/plan",
        payload=_envelope("hive/cognitive/prefrontal/plan", "prefrontal_cortex", {"x": 1}),
    )
    await sub.dispatch(msg)

    [rec] = ring.snapshot()
    assert rec.destinations == ("thalamus",)


@pytest.mark.asyncio
async def test_non_json_payload_is_logged_and_skipped() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(topic="hive/hardware/mic", payload=b"\x00\x01\x02raw-audio")
    await sub.dispatch(msg)  # must not raise
    # nothing recorded — raw binary is out of scope for v1 visualization
    assert len(ring) == 0


def test_subscription_map_from_dir(tmp_path) -> None:
    from observatory.mqtt_subscriber import load_subscription_map  # noqa: PLC0415

    (tmp_path / "regions").mkdir()
    r = tmp_path / "regions" / "thalamus"
    r.mkdir()
    (r / "subscriptions.yaml").write_text(
        "topics:\n  - hive/cognitive/prefrontal/plan\n  - hive/sensory/auditory/text\n",
        encoding="utf-8",
    )
    m = load_subscription_map(tmp_path)
    assert m == {"thalamus": ["hive/cognitive/prefrontal/plan", "hive/sensory/auditory/text"]}


def test_subscription_map_malformed_yaml_in_one_region_is_not_fatal(tmp_path) -> None:
    """One region's broken YAML must not poison the rest of the map."""
    from observatory.mqtt_subscriber import load_subscription_map  # noqa: PLC0415

    (tmp_path / "regions").mkdir()
    good = tmp_path / "regions" / "thalamus"
    good.mkdir()
    (good / "subscriptions.yaml").write_text(
        "topics:\n  - hive/cognitive/prefrontal/plan\n", encoding="utf-8"
    )
    bad = tmp_path / "regions" / "hippocampus"
    bad.mkdir()
    # YAML with an unterminated string — guaranteed parse error
    (bad / "subscriptions.yaml").write_text("topics:\n  - 'unterminated\n", encoding="utf-8")

    m = load_subscription_map(tmp_path)
    assert m == {"thalamus": ["hive/cognitive/prefrontal/plan"]}


def test_subscription_map_non_string_topic_items_are_filtered(tmp_path) -> None:
    from observatory.mqtt_subscriber import load_subscription_map  # noqa: PLC0415

    (tmp_path / "regions").mkdir()
    r = tmp_path / "regions" / "cerebellum"
    r.mkdir()
    (r / "subscriptions.yaml").write_text(
        "topics:\n  - hive/ok/topic\n  - 42\n  - {}\n",
        encoding="utf-8",
    )
    m = load_subscription_map(tmp_path)
    assert m == {"cerebellum": ["hive/ok/topic"]}


def test_subscription_map_non_list_topics_is_not_fatal(tmp_path) -> None:
    from observatory.mqtt_subscriber import load_subscription_map  # noqa: PLC0415

    (tmp_path / "regions").mkdir()
    r = tmp_path / "regions" / "thalamus"
    r.mkdir()
    (r / "subscriptions.yaml").write_text(
        "topics: hive/cognitive/plan\n",  # scalar, not a list
        encoding="utf-8",
    )
    m = load_subscription_map(tmp_path)
    assert m == {}


# ---------------------------------------------------------------------------
# MQTT wildcard semantics (_matches / _mqtt_pattern_to_regex)
# ---------------------------------------------------------------------------

def test_plus_wildcard_matches_exactly_one_segment() -> None:
    from observatory.mqtt_subscriber import _matches  # noqa: PLC0415

    # Single-level + must match exactly one segment — NOT cross ``/``.
    assert _matches("hive/cognitive/plan", "hive/+/plan") is True
    assert _matches("hive/a/b/plan", "hive/+/plan") is False
    assert _matches("hive/plan", "hive/+/plan") is False


def test_hash_wildcard_matches_multiple_segments_only_at_end() -> None:
    from observatory.mqtt_subscriber import _matches  # noqa: PLC0415

    assert _matches("hive/cognitive/prefrontal/plan", "hive/#") is True
    assert _matches("hive/a", "hive/#") is True
    # # only valid at end — malformed filters match nothing
    assert _matches("hive/x/y", "hive/#/y") is False


def test_exact_topic_filter_is_literal() -> None:
    from observatory.mqtt_subscriber import _matches  # noqa: PLC0415

    assert _matches("hive/cognitive/plan", "hive/cognitive/plan") is True
    assert _matches("hive/cognitive/plans", "hive/cognitive/plan") is False


# ---------------------------------------------------------------------------
# Source-missing + heartbeat edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_source_region_yields_empty_destinations() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub_map = {"thalamus": ["hive/cognitive/prefrontal/plan"]}
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map=sub_map)

    # Envelope without source_region — no trustworthy inference.
    payload = json.dumps({
        "id": "x",
        "timestamp": "2026-04-20T00:00:00.000Z",
        "topic": "hive/cognitive/prefrontal/plan",
        "payload": {"x": 1},
        # no "source_region" key
    }).encode()
    msg = FakeMsg(topic="hive/cognitive/prefrontal/plan", payload=payload)
    await sub.dispatch(msg)

    [rec] = ring.snapshot()
    assert rec.source_region is None
    assert rec.destinations == ()


@pytest.mark.asyncio
async def test_heartbeat_with_missing_payload_key_is_noop() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    # Envelope whose "payload" is missing entirely — dispatch must not raise
    # and registry stats must stay at their defaults.
    payload = json.dumps({
        "id": "x",
        "timestamp": "2026-04-20T00:00:00.000Z",
        "source_region": "thalamus",
        "topic": "hive/system/heartbeat/thalamus",
        # no "payload" key
    }).encode()
    msg = FakeMsg(topic="hive/system/heartbeat/thalamus", payload=payload)
    await sub.dispatch(msg)

    # The heartbeat was skipped silently; registry still has thalamus at defaults
    # (auto-registered via apply_heartbeat only if we'd called it).
    assert "thalamus" not in reg.names()
    # But the envelope still landed in the ring.
    assert len(ring) == 1


@pytest.mark.asyncio
async def test_heartbeat_wrapped_non_dict_data_is_skipped() -> None:
    """A wrapped envelope whose ``data`` is non-dict (e.g. a counter scalar)
    carries no heartbeat stats — the registry must not be touched."""
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/system/heartbeat/thalamus",
        payload=_envelope(
            "hive/system/heartbeat/thalamus",
            "thalamus",
            {"content_type": "application/hive+counter", "data": 42, "encoding": "utf-8"},
        ),
    )
    await sub.dispatch(msg)
    assert "thalamus" not in reg.names()
    assert len(ring) == 1  # envelope still recorded for traffic view
