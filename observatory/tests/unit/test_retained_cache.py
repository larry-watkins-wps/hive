"""Retained cache invariants."""
from __future__ import annotations

from observatory.retained_cache import RetainedCache


def _env(topic: str, payload: dict) -> dict:
    return {"topic": topic, "payload": payload}


def test_put_and_get_latest_envelope() -> None:
    cache = RetainedCache()
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {"v": 0.4}))
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {"v": 0.7}))
    got = cache.get("hive/modulator/cortisol")
    assert got is not None
    assert got["payload"]["v"] == 0.7  # noqa: PLR2004


def test_missing_topic_returns_none() -> None:
    cache = RetainedCache()
    assert cache.get("hive/nope") is None


def test_snapshot_returns_immutable_copy() -> None:
    cache = RetainedCache()
    cache.put("a", _env("a", {"x": 1}))
    cache.put("b", _env("b", {"x": 2}))
    snap = cache.snapshot()
    assert set(snap.keys()) == {"a", "b"}
    # mutating snap must not affect cache
    snap["c"] = _env("c", {"x": 3})
    assert cache.get("c") is None


def test_keys_matching_prefix() -> None:
    cache = RetainedCache()
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {}))
    cache.put("hive/modulator/dopamine", _env("hive/modulator/dopamine", {}))
    cache.put("hive/self/identity", _env("hive/self/identity", {}))
    got = sorted(cache.keys_matching("hive/modulator/"))
    assert got == ["hive/modulator/cortisol", "hive/modulator/dopamine"]
