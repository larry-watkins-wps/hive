"""Tests for region_template.memory — spec §D.2 (STM), §D.3 (LTM), §D.4 (Index).

Covers:

STM (§D.2):
  - Fresh store has empty slots + recent_events
  - write_stm + read_stm round-trips the value
  - Upsert semantics (second write wins)
  - delete_stm returns True/False
  - list_stm with/without tag filter
  - TTL expiry — lazy eviction on read_stm / list_stm
  - sweep_expired() explicit method
  - record_event ring-buffer cap
  - stm_size_bytes returns serialized JSON length
  - Stage-1 overflow: trims recent_events when it dominates the budget
  - Stage-2 overflow: raises StmOverflow when trim is insufficient
  - Atomic write-rename survives os.replace failure
  - Persistence: new MemoryStore sees previously written slot
  - Corrupt stm.json: quarantined, fresh empty state

LTM (§D.3):
  - write_ltm creates a markdown file with front-matter + body
  - write_ltm append prepends a new section and preserves created_at
  - write_ltm updates updated_at on append
  - query_ltm ranks by term matches
  - @sleep_only gating: PhaseViolation during WAKE

Index (§D.4):
  - build_index walks ltm/, produces documents + postings
  - Empty ltm/: valid empty index
  - Rebuild idempotency

Concurrency:
  - Two concurrent write_stm coroutines serialize cleanly
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from region_template import memory as memmod
from region_template.errors import PhaseViolation, StmOverflow
from region_template.memory import (
    LtmMetadata,
    MemoryQuery,
    MemoryStore,
    OriginRef,
)
from region_template.types import LifecyclePhase
from shared.message_envelope import Envelope

# Magic-number constants keep ruff PLR2004 quiet and make intent explicit.
_TTL_SHORT_S = 60
_EVENT_CAP_SMALL = 3
_EVENTS_AT_LEAST = 8
_QUERY_MIN_HITS = 2
_SUN1_SUNSET_COUNT = 2
_SUN1_WARMTH_COUNT = 3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(
    tmp_path: Path,
    *,
    phase: LifecyclePhase = LifecyclePhase.SLEEP,
    stm_max_bytes: int = 4096,
    recent_events_max: int = 10,
) -> MemoryStore:
    runtime_fake = SimpleNamespace(phase=phase)
    return MemoryStore(
        root=tmp_path / "memory",
        region_name="test_region",
        stm_max_bytes=stm_max_bytes,
        recent_events_max=recent_events_max,
        runtime=runtime_fake,
    )


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return _make_store(tmp_path)


def _envelope(source: str = "test_region", topic: str = "t/x") -> Envelope:
    return Envelope.new(
        source_region=source,
        topic=topic,
        content_type="text/plain",
        data="hello",
    )


# ---------------------------------------------------------------------------
# STM — construction + empty state
# ---------------------------------------------------------------------------


async def test_fresh_store_has_empty_slots_and_events(store: MemoryStore) -> None:
    assert await store.read_stm("nope") is None
    assert await store.list_stm() == []
    # stm.json should not yet exist on disk (lazy creation)
    # but stm_size_bytes still returns something sensible.
    assert await store.stm_size_bytes() >= 0


async def test_construction_creates_directories(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / "memory" / "ltm").is_dir()
    # Touch the store to avoid ruff unused-var warnings.
    assert await store.read_stm("x") is None


# ---------------------------------------------------------------------------
# STM — write / read / upsert
# ---------------------------------------------------------------------------


async def test_write_then_read_round_trips_value(store: MemoryStore) -> None:
    await store.write_stm("goal", {"id": 1, "name": "paint"})
    slot = await store.read_stm("goal")
    assert slot is not None
    assert slot.value == {"id": 1, "name": "paint"}


async def test_write_stm_records_origin_and_tags(store: MemoryStore) -> None:
    origin = OriginRef(topic="a/b", envelope_id="env-1", correlation_id="cor-1")
    await store.write_stm(
        "focus",
        "text",
        origin=origin,
        ttl_s=_TTL_SHORT_S,
        tags=["goal", "current"],
    )
    slot = await store.read_stm("focus")
    assert slot is not None
    assert slot.origin == origin
    assert slot.ttl_s == _TTL_SHORT_S
    assert set(slot.tags) == {"goal", "current"}


async def test_upsert_second_write_wins(store: MemoryStore) -> None:
    await store.write_stm("k", "v1")
    await store.write_stm("k", "v2")
    slot = await store.read_stm("k")
    assert slot is not None
    assert slot.value == "v2"


# ---------------------------------------------------------------------------
# STM — delete
# ---------------------------------------------------------------------------


async def test_delete_stm_returns_true_for_existing_key(store: MemoryStore) -> None:
    await store.write_stm("k", "v")
    assert await store.delete_stm("k") is True
    assert await store.read_stm("k") is None


async def test_delete_stm_returns_false_for_missing_key(store: MemoryStore) -> None:
    assert await store.delete_stm("nope") is False


# ---------------------------------------------------------------------------
# STM — list + tag filter
# ---------------------------------------------------------------------------


async def test_list_stm_returns_all_slots_with_no_filter(store: MemoryStore) -> None:
    await store.write_stm("a", 1, tags=["x"])
    await store.write_stm("b", 2, tags=["y"])
    slots = await store.list_stm()
    values = sorted(s.value for s in slots)
    assert values == [1, 2]


async def test_list_stm_filters_by_tag(store: MemoryStore) -> None:
    await store.write_stm("a", 1, tags=["goal"])
    await store.write_stm("b", 2, tags=["goal", "urgent"])
    await store.write_stm("c", 3, tags=["other"])
    slots = await store.list_stm(tag="goal")
    assert sorted(s.value for s in slots) == [1, 2]


# ---------------------------------------------------------------------------
# STM — TTL handling
# ---------------------------------------------------------------------------


async def test_read_stm_returns_none_for_expired_slot(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Freeze "now" at t0, write with ttl_s=1. Then advance past expiry.
    t0 = 1_000_000.0
    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0)
    await store.write_stm("ephemeral", "v", ttl_s=1)

    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0 + 5)
    assert await store.read_stm("ephemeral") is None


async def test_list_stm_omits_expired_slots(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = 1_000_000.0
    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0)
    await store.write_stm("keep", "k")
    await store.write_stm("drop", "d", ttl_s=1)

    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0 + 10)
    values = [s.value for s in await store.list_stm()]
    assert values == ["k"]


async def test_sweep_expired_removes_expired_slots_from_disk(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = 1_000_000.0
    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0)
    await store.write_stm("live", "l")
    await store.write_stm("dead", "d", ttl_s=1)

    monkeypatch.setattr(memmod, "_monotonic_now", lambda: t0 + 5)
    removed = await store.sweep_expired()
    assert removed == 1

    # Confirm disk state no longer mentions "dead".
    text = (store.root / "stm.json").read_text(encoding="utf-8")
    assert "dead" not in text
    assert "live" in text


# ---------------------------------------------------------------------------
# STM — record_event ring buffer
# ---------------------------------------------------------------------------


async def test_record_event_appends_and_caps(tmp_path: Path) -> None:
    store = _make_store(tmp_path, recent_events_max=_EVENT_CAP_SMALL)
    for i in range(5):
        env = _envelope(topic=f"t/{i}")
        await store.record_event(env, summary=f"event {i}")
    events = await store.recent_events()
    assert len(events) == _EVENT_CAP_SMALL
    # Oldest (t/0, t/1) are dropped; newest (t/2, t/3, t/4) remain.
    topics = [e["topic"] for e in events]
    assert topics == ["t/2", "t/3", "t/4"]


# ---------------------------------------------------------------------------
# STM — size accounting
# ---------------------------------------------------------------------------


async def test_stm_size_bytes_matches_serialized_length(store: MemoryStore) -> None:
    await store.write_stm("k", "v")
    raw = (store.root / "stm.json").read_bytes()
    assert await store.stm_size_bytes() == len(raw)


# ---------------------------------------------------------------------------
# STM — two-stage overflow (§D.2.4)
# ---------------------------------------------------------------------------


async def test_overflow_stage1_trims_recent_events(tmp_path: Path) -> None:
    """When recent_events occupies > half the budget, a new write trims 50% of events.

    The test tunes the budget so that one 50%-trim brings size back under the cap.
    Per §D.2.4: stage-1 trims oldest 50%; if still over, stage-2 raises.
    """
    store = _make_store(tmp_path, stm_max_bytes=6144, recent_events_max=100)
    # Fill recent_events with fat summaries until they dominate half the budget
    # but not so much that a single 50% trim can't bring us under.
    fat = "x" * 200
    for i in range(20):
        env = _envelope(topic=f"t/{i}")
        await store.record_event(env, summary=fat)
    before = len(await store.recent_events())
    assert before >= _EVENTS_AT_LEAST  # plenty present

    # A small slot write should trigger stage-1 trim (rather than raise).
    await store.write_stm("k", "v")
    after = len(await store.recent_events())
    assert after < before
    assert after <= before // 2 + 1  # trimmed ~50%


async def test_overflow_stage2_raises_stm_overflow(tmp_path: Path) -> None:
    """With few recent_events, an over-budget slot write raises StmOverflow."""
    store = _make_store(tmp_path, stm_max_bytes=512, recent_events_max=10)
    # One tiny event — nowhere near half the budget.
    await store.record_event(_envelope(), summary="tiny")

    huge_value = "y" * 4096  # way past the 512-byte cap
    with pytest.raises(StmOverflow):
        await store.write_stm("big", huge_value)


async def test_overflow_failed_write_does_not_corrupt_store(tmp_path: Path) -> None:
    """Stage-2 overflow must leave prior persisted state intact."""
    store = _make_store(tmp_path, stm_max_bytes=512, recent_events_max=10)
    await store.write_stm("good", "small")
    with pytest.raises(StmOverflow):
        await store.write_stm("bad", "z" * 4096)

    # 'good' still readable; 'bad' absent.
    good = await store.read_stm("good")
    assert good is not None
    assert good.value == "small"
    assert await store.read_stm("bad") is None


# ---------------------------------------------------------------------------
# STM — atomic write-rename survives partial failure
# ---------------------------------------------------------------------------


async def test_os_replace_failure_leaves_stm_intact(
    store: MemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await store.write_stm("k", "original")
    stm_path = store.root / "stm.json"
    snapshot = stm_path.read_bytes()

    def _boom(src: str, dst: str) -> None:  # noqa: ARG001
        raise OSError("simulated replace failure")

    monkeypatch.setattr(memmod.os, "replace", _boom)
    with pytest.raises(OSError, match="simulated"):
        await store.write_stm("k", "overwritten")

    # File unchanged on disk.
    assert stm_path.read_bytes() == snapshot


# ---------------------------------------------------------------------------
# STM — persistence across constructions
# ---------------------------------------------------------------------------


async def test_stm_persists_across_constructions(tmp_path: Path) -> None:
    s1 = _make_store(tmp_path)
    await s1.write_stm("k", {"a": 1})

    s2 = _make_store(tmp_path)
    slot = await s2.read_stm("k")
    assert slot is not None
    assert slot.value == {"a": 1}


# ---------------------------------------------------------------------------
# STM — corrupt file recovery
# ---------------------------------------------------------------------------


async def test_corrupt_stm_quarantined_and_fresh_state(tmp_path: Path) -> None:
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    stm_path = tmp_path / "memory" / "stm.json"
    stm_path.write_text("{ this is not valid json", encoding="utf-8")

    store = _make_store(tmp_path)
    # Fresh empty state.
    assert await store.read_stm("any") is None
    # The corrupt file was moved aside.
    corrupt = list((tmp_path / "memory").glob("stm.json.corrupt.*"))
    assert len(corrupt) == 1


# ---------------------------------------------------------------------------
# STM — concurrency (asyncio.Lock)
# ---------------------------------------------------------------------------


async def test_concurrent_writes_serialize_cleanly(store: MemoryStore) -> None:
    await asyncio.gather(
        store.write_stm("a", 1),
        store.write_stm("b", 2),
        store.write_stm("c", 3),
        store.write_stm("d", 4),
    )
    slots = await store.list_stm()
    values = sorted(s.value for s in slots)
    assert values == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# LTM — write_ltm creates files
# ---------------------------------------------------------------------------


async def test_write_ltm_creates_file_with_frontmatter(store: MemoryStore) -> None:
    meta = LtmMetadata(
        topic="sunset_paintings",
        tags=["painting", "visual"],
        importance=0.7,
        emotional_tag="positive",
    )
    result = await store.write_ltm(
        path="episodes/2026-04-19T001.md",
        content="Painted a sunset today. The orange was warm.",
        metadata=meta,
        reason="first sunset",
    )
    assert result.created is True
    target = store.root / "ltm" / "episodes" / "2026-04-19T001.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "topic: sunset_paintings" in text
    assert "importance: 0.7" in text
    assert "emotional_tag: positive" in text
    assert "Painted a sunset today" in text


async def test_write_ltm_append_prepends_new_section(store: MemoryStore) -> None:
    meta = LtmMetadata(
        topic="t",
        tags=[],
        importance=0.5,
        emotional_tag=None,
    )
    await store.write_ltm("knowledge/t.md", "first note", meta, reason="r1")
    result2 = await store.write_ltm(
        "knowledge/t.md", "second note", meta, reason="r2"
    )
    assert result2.created is False
    text = (store.root / "ltm" / "knowledge" / "t.md").read_text(encoding="utf-8")
    # New section appears before older one.
    idx_second = text.index("second note")
    idx_first = text.index("first note")
    assert idx_second < idx_first


async def test_write_ltm_preserves_created_at_updates_updated_at(store: MemoryStore) -> None:
    meta = LtmMetadata(
        topic="t",
        tags=[],
        importance=0.5,
        emotional_tag=None,
    )
    await store.write_ltm("knowledge/x.md", "a", meta, reason="r1")
    text1 = (store.root / "ltm" / "knowledge" / "x.md").read_text(encoding="utf-8")
    # Extract created_at from the first write's front-matter.
    created_1 = _frontmatter_field(text1, "created_at")
    updated_1 = _frontmatter_field(text1, "updated_at")
    assert created_1 == updated_1  # fresh file

    # A tiny sleep to ensure the updated_at timestamp changes.
    await asyncio.sleep(0.01)
    await store.write_ltm("knowledge/x.md", "b", meta, reason="r2")
    text2 = (store.root / "ltm" / "knowledge" / "x.md").read_text(encoding="utf-8")
    created_2 = _frontmatter_field(text2, "created_at")
    updated_2 = _frontmatter_field(text2, "updated_at")
    assert created_2 == created_1  # preserved
    assert updated_2 != updated_1  # bumped


def _frontmatter_field(text: str, key: str) -> str:
    """Pull `key: value` out of a YAML-ish front-matter block (tests only)."""
    assert text.startswith("---")
    end = text.index("---", 3)
    header = text[3:end]
    for line in header.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"front-matter key {key} not found")


# ---------------------------------------------------------------------------
# LTM — query ordering
# ---------------------------------------------------------------------------


async def test_query_ltm_ranks_by_term_match(store: MemoryStore) -> None:
    meta_a = LtmMetadata(topic="sunsets", tags=["art"], importance=0.9,
                         emotional_tag="positive")
    meta_b = LtmMetadata(topic="sunsets", tags=["art"], importance=0.1,
                         emotional_tag=None)
    await store.write_ltm(
        "episodes/sunset_a.md",
        "sunset sunset sunset orange orange warmth",
        meta_a,
        reason="r",
    )
    await store.write_ltm(
        "episodes/sunset_b.md",
        "sunset briefly mentioned once among many unrelated things",
        meta_b,
        reason="r",
    )
    hits = await store.query_ltm(
        MemoryQuery(
            question="sunset orange",
            topics=[],
            timeframe_hint=None,
            max_results=10,
        )
    )
    assert len(hits) >= _QUERY_MIN_HITS
    # First hit should be sunset_a (higher term count + higher importance).
    assert "sunset_a" in hits[0].source
    # Confidence decreases along the ranking.
    confidences = [h.confidence for h in hits]
    assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# LTM — @sleep_only gating
# ---------------------------------------------------------------------------


async def test_write_ltm_requires_sleep_phase(tmp_path: Path) -> None:
    store = _make_store(tmp_path, phase=LifecyclePhase.WAKE)
    meta = LtmMetadata(topic="t", tags=[], importance=0.5, emotional_tag=None)
    with pytest.raises(PhaseViolation):
        await store.write_ltm("episodes/x.md", "body", meta, reason="r")


async def test_query_ltm_requires_sleep_phase(tmp_path: Path) -> None:
    store = _make_store(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await store.query_ltm(
            MemoryQuery(question="q", topics=[], timeframe_hint=None, max_results=5)
        )


async def test_build_index_requires_sleep_phase(tmp_path: Path) -> None:
    store = _make_store(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await store.build_index()


# ---------------------------------------------------------------------------
# Index (§D.4)
# ---------------------------------------------------------------------------


async def test_build_index_empty_ltm_produces_valid_empty_index(store: MemoryStore) -> None:
    idx = await store.build_index()
    assert idx["schema_version"] == 1
    assert idx["documents"] == {}
    assert idx["postings"] == {}
    # index.json also written to disk.
    on_disk = json.loads((store.root / "index.json").read_text(encoding="utf-8"))
    assert on_disk["documents"] == {}


async def test_build_index_walks_ltm_and_builds_postings(store: MemoryStore) -> None:
    meta = LtmMetadata(topic="sunset_paintings", tags=["painting", "visual"],
                       importance=0.7, emotional_tag="positive")
    await store.write_ltm(
        "episodes/sun1.md",
        "sunset sunset orange warmth warmth warmth",
        meta,
        reason="r",
    )
    await store.write_ltm(
        "episodes/sun2.md",
        "sunset moon stars",
        meta,
        reason="r",
    )

    idx = await store.build_index()
    docs = idx["documents"]
    assert "episodes/sun1.md" in docs
    assert docs["episodes/sun1.md"]["topic"] == "sunset_paintings"
    assert docs["episodes/sun1.md"]["term_counts"]["sunset"] == _SUN1_SUNSET_COUNT
    assert docs["episodes/sun1.md"]["term_counts"]["warmth"] == _SUN1_WARMTH_COUNT

    postings = idx["postings"]
    assert set(postings["sunset"]) == {"episodes/sun1.md", "episodes/sun2.md"}
    assert postings["orange"] == ["episodes/sun1.md"]


async def test_build_index_is_idempotent(store: MemoryStore) -> None:
    meta = LtmMetadata(topic="t", tags=["x"], importance=0.5, emotional_tag=None)
    await store.write_ltm("knowledge/a.md", "alpha beta gamma alpha", meta, reason="r")
    idx_a = await store.build_index()
    idx_b = await store.build_index()
    # built_at will differ — compare the content fields.
    assert idx_a["documents"] == idx_b["documents"]
    assert idx_a["postings"] == idx_b["postings"]


# ---------------------------------------------------------------------------
# Sanity: os import for monkeypatch tests uses Memory's module path.
# ---------------------------------------------------------------------------


def test_memory_module_exports_os_attribute() -> None:
    """Confirms the monkeypatch target exists on the module."""
    assert hasattr(memmod, "os")
    assert memmod.os is os
