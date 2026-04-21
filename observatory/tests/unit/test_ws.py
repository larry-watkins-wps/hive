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
from observatory.ws import _QUEUE_HIGH_WATER, ConnectionHub, _Client, build_ws_router


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
