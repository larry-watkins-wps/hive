"""Unit tests for ``observatory.ws``.

Repair strategy Option B (see ``observatory/memory/decisions.md`` 2026-04-20):
the plan's Step-1 test mixed a Starlette ``TestClient`` (which runs FastAPI in
its own thread + event loop) with a main-thread ``asyncio.get_event_loop().
run_until_complete(...)`` call. In Python 3.12, that cross-loop pattern either
silently hangs or raises "got Future attached to a different loop". We split
the plan's single mixed test into three cleaner tests:

* ``test_snapshot_message_shape_unit`` — pure unit test of
  ``ConnectionHub.snapshot_message()`` (no WS, no TestClient, no event loops).
* ``test_snapshot_on_connect_via_testclient`` — WS-level test that
  ``build_ws_router`` + ``hub.serve`` wire the snapshot onto connect.
* ``test_broadcast_envelope_enqueues_on_client`` — pure async test that
  ``broadcast_envelope`` puts the expected envelope message onto a
  manually-constructed ``_Client.queue``, without touching the WS plumbing.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from observatory.adjacency import Adjacency
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord
from observatory.ws import (
    _QUEUE_HIGH_WATER,
    ConnectionHub,
    _Client,
    build_ws_router,
)


@pytest.fixture
def pieces():
    ring = RingBuffer(capacity=100)
    cache = RetainedCache()
    cache.put(
        "hive/modulator/cortisol",
        {"topic": "hive/modulator/cortisol", "payload": {"value": 0.3}},
    )
    reg = RegionRegistry()
    reg.apply_heartbeat(
        "thalamus",
        {
            "phase": "wake",
            "queue_depth_messages": 0,
            "stm_bytes": 0,
            "llm_tokens_used_lifetime": 0,
            "handler_count": 0,
            "last_error_ts": None,
        },
    )
    adj = Adjacency(window_seconds=5.0)
    hub = ConnectionHub(
        ring=ring, cache=cache, registry=reg, adjacency=adj, max_ws_rate=200
    )
    return hub, ring, cache, reg, adj


def test_snapshot_message_shape_unit(pieces) -> None:
    hub, _ring, _cache, _reg, _adj = pieces
    msg = hub.snapshot_message()
    assert msg["type"] == "snapshot"
    p = msg["payload"]
    assert "regions" in p and "thalamus" in p["regions"]
    assert "retained" in p and "hive/modulator/cortisol" in p["retained"]
    assert "recent" in p
    assert isinstance(p["recent"], list)
    assert "server_version" in p
    assert "baseline_pairs" in p
    assert isinstance(p["baseline_pairs"], list)


def test_snapshot_baseline_pairs_reflects_recent_traffic(pieces) -> None:
    """Baseline pairs come from the adjacency's windowed recent set (not
    the complete graph). Fresh fixture → empty. After traffic flows, the
    pairs that fired (within the baseline window) appear canonicalised."""
    import time as _time

    hub, _ring, _cache, _reg, adj = pieces
    assert hub.snapshot_message()["payload"]["baseline_pairs"] == []

    # Record at "now" (real monotonic clock) so the 30 s baseline window
    # inside recent_pairs() contains the pair when snapshot_message fires.
    adj.record("thalamus", ["amygdala", "vta"], now=_time.monotonic())
    pairs = hub.snapshot_message()["payload"]["baseline_pairs"]
    assert pairs == [["amygdala", "thalamus"], ["thalamus", "vta"]]


def test_snapshot_on_connect_via_testclient(pieces) -> None:
    hub, _ring, _cache, _reg, _adj = pieces
    app = FastAPI()
    app.include_router(build_ws_router(hub))
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        p = msg["payload"]
        assert "regions" in p and "thalamus" in p["regions"]
        assert "retained" in p and "hive/modulator/cortisol" in p["retained"]
        assert "recent" in p
        assert "server_version" in p


@pytest.mark.asyncio
async def test_broadcast_envelope_enqueues_on_client(pieces) -> None:
    """Exercise the fan-out path directly, bypassing the WS transport.

    Construct a ``_Client`` manually, register it on the hub, then call
    ``broadcast_envelope`` in the same event loop. Asserts the enqueued
    message has the expected shape and that ``destinations`` has been
    converted from ``tuple[str, ...]`` to ``list[str]`` for JSON.
    """
    hub, _ring, _cache, _reg, _adj = pieces
    client = _Client(ws=None)  # type: ignore[arg-type]
    hub._clients.add(client)

    rec = RingRecord(
        observed_at=1.0,
        topic="hive/cognitive/prefrontal/plan",
        envelope={"id": "x"},
        source_region="thalamus",
        destinations=("prefrontal_cortex",),
    )
    await hub.broadcast_envelope(rec)

    queued = client.queue.get_nowait()
    assert queued["type"] == "envelope"
    assert queued["payload"]["topic"] == "hive/cognitive/prefrontal/plan"
    assert queued["payload"]["source_region"] == "thalamus"
    assert queued["payload"]["destinations"] == ["prefrontal_cortex"]
    assert queued["payload"]["envelope"] == {"id": "x"}
    assert queued["payload"]["observed_at"] == 1.0


@pytest.mark.asyncio
async def test_broadcast_envelope_drops_when_queue_above_high_water(pieces) -> None:
    """Slow-client protection: once ``queue.qsize() > _QUEUE_HIGH_WATER``, drop."""
    hub, _ring, _cache, _reg, _adj = pieces
    client = _Client(ws=None)  # type: ignore[arg-type]
    # Pre-fill over the high-water mark.
    for _ in range(_QUEUE_HIGH_WATER + 1):
        client.queue.put_nowait({"type": "filler"})
    hub._clients.add(client)

    baseline = client.queue.qsize()
    rec = RingRecord(
        observed_at=2.0,
        topic="hive/x",
        envelope={},
        source_region="a",
        destinations=("b",),
    )
    await hub.broadcast_envelope(rec)
    # Queue size unchanged — drop path exercised.
    assert client.queue.qsize() == baseline
    # Drop counter incremented so the next delta tick can emit `decimated`.
    assert client.dropped_since_last_delta == 1


@pytest.mark.asyncio
async def test_broadcast_envelope_increments_drop_counter_when_decimator_rejects(
    pieces,
) -> None:
    """When the per-client decimator says `should_keep=False`, the drop is
    counted on the client (so ``_delta_loop`` can surface it via
    ``decimated``) but nothing lands on the queue."""
    from observatory.decimator import Decimator  # noqa: PLC0415

    hub, _ring, _cache, _reg, _adj = pieces
    # max_rate=1 → second envelope in the same 1s window is rejected.
    client = _Client(ws=None, decimator=Decimator(max_rate=1))  # type: ignore[arg-type]
    hub._clients.add(client)

    rec = RingRecord(
        observed_at=1.0,
        topic="hive/x",
        envelope={},
        source_region="a",
        destinations=("b",),
    )
    await hub.broadcast_envelope(rec)
    await hub.broadcast_envelope(rec)
    # First kept, second rejected by the decimator.
    assert client.queue.qsize() == 1
    assert client.dropped_since_last_delta == 1


@pytest.mark.asyncio
async def test_delta_loop_emits_decimated_message_when_drops_accumulated(
    pieces, monkeypatch
) -> None:
    """After an envelope drop, the next `_delta_loop` tick should enqueue a
    `decimated` message for that client and reset the counter."""
    import observatory.ws as ws_module  # noqa: PLC0415

    # Make the delta loop tick immediately.
    monkeypatch.setattr(ws_module, "_DELTA_INTERVAL_S", 0.0)

    hub, _ring, _cache, _reg, _adj = pieces
    client = _Client(ws=None)  # type: ignore[arg-type]
    client.dropped_since_last_delta = 5  # pretend 5 envelopes were dropped
    hub._clients.add(client)

    # Run one iteration of the delta loop body by driving it directly.
    task = __import__("asyncio").create_task(hub._delta_loop())
    try:
        # Wait until the client has received the three expected messages.
        for _ in range(50):  # up to ~1 s
            if client.queue.qsize() >= 3:  # noqa: PLR2004 — adjacency + region_delta + decimated
                break
            await __import__("asyncio").sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except __import__("asyncio").CancelledError:
            pass

    msgs = []
    while not client.queue.empty():
        msgs.append(client.queue.get_nowait())
    types = [m["type"] for m in msgs]
    assert "decimated" in types
    decimated = next(m for m in msgs if m["type"] == "decimated")
    assert decimated["payload"]["dropped"] == 5  # noqa: PLR2004
    # Counter reset after emit.
    assert client.dropped_since_last_delta == 0


@pytest.mark.asyncio
async def test_delta_loop_survives_transient_exception(pieces, monkeypatch) -> None:
    """A raise inside the body of `_delta_loop` must not kill the loop —
    subsequent ticks should continue delivering deltas."""
    import observatory.ws as ws_module  # noqa: PLC0415

    monkeypatch.setattr(ws_module, "_DELTA_INTERVAL_S", 0.0)

    hub, _ring, _cache, _reg, _adj = pieces
    client = _Client(ws=None)  # type: ignore[arg-type]
    hub._clients.add(client)

    # Arrange: make the registry's to_json() raise once, then succeed.
    calls = {"n": 0}
    orig_to_json = hub.registry.to_json

    def flaky_to_json() -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated snapshot failure")
        return orig_to_json()

    monkeypatch.setattr(hub.registry, "to_json", flaky_to_json)

    task = __import__("asyncio").create_task(hub._delta_loop())
    try:
        # Wait for at least one successful tick after the failure.
        for _ in range(100):  # up to ~2 s
            if client.queue.qsize() > 0 and calls["n"] >= 2:  # noqa: PLR2004
                break
            await __import__("asyncio").sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except __import__("asyncio").CancelledError:
            pass

    # After the first (failing) tick plus at least one successful one, some
    # delta messages made it to the queue.
    assert calls["n"] >= 2  # noqa: PLR2004
    assert client.queue.qsize() > 0


@pytest.mark.asyncio
async def test_delta_loop_does_not_stall_on_full_queue(pieces, monkeypatch) -> None:
    """A single stalled/over-full client must not block delta delivery to
    other clients."""
    import observatory.ws as ws_module  # noqa: PLC0415

    monkeypatch.setattr(ws_module, "_DELTA_INTERVAL_S", 0.0)

    hub, _ring, _cache, _reg, _adj = pieces

    slow = _Client(ws=None)  # type: ignore[arg-type]
    # Pre-fill slow client beyond the high-water mark.
    for _ in range(_QUEUE_HIGH_WATER + 1):
        slow.queue.put_nowait({"type": "filler"})
    fast = _Client(ws=None)  # type: ignore[arg-type]
    hub._clients.add(slow)
    hub._clients.add(fast)

    slow_baseline = slow.queue.qsize()

    task = __import__("asyncio").create_task(hub._delta_loop())
    try:
        for _ in range(100):
            if fast.queue.qsize() >= 2:  # noqa: PLR2004 — adjacency + region_delta
                break
            await __import__("asyncio").sleep(0.02)
    finally:
        task.cancel()
        try:
            await task
        except __import__("asyncio").CancelledError:
            pass

    # Fast client received deltas.
    assert fast.queue.qsize() >= 2  # noqa: PLR2004
    # Slow client's queue did NOT grow via the delta loop (dropped silently).
    assert slow.queue.qsize() == slow_baseline
