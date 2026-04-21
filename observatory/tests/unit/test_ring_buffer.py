"""Ring buffer invariants."""
from __future__ import annotations

import pytest

from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord


def _rec(i: int) -> RingRecord:
    return RingRecord(
        observed_at=float(i),
        topic=f"hive/test/{i}",
        envelope={"id": i},
        source_region=None,
        destinations=(),
    )


def test_append_within_capacity_preserves_order() -> None:
    buf = RingBuffer(capacity=5)
    for i in range(3):
        buf.append(_rec(i))
    assert [r.envelope["id"] for r in buf.snapshot()] == [0, 1, 2]


def test_append_beyond_capacity_drops_oldest() -> None:
    buf = RingBuffer(capacity=3)
    for i in range(5):
        buf.append(_rec(i))
    assert [r.envelope["id"] for r in buf.snapshot()] == [2, 3, 4]


def test_snapshot_returns_tuple_not_internal_deque() -> None:
    buf = RingBuffer(capacity=3)
    buf.append(_rec(0))
    snap = buf.snapshot()
    assert isinstance(snap, tuple)


def test_len_reflects_count() -> None:
    buf = RingBuffer(capacity=10)
    assert len(buf) == 0
    for i in range(4):
        buf.append(_rec(i))
    assert len(buf) == 4  # noqa: PLR2004


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RingBuffer(capacity=0)
    with pytest.raises(ValueError):
        RingBuffer(capacity=-1)
