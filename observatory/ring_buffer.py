"""Bounded ring of RingRecord with snapshot access."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from observatory.types import RingRecord


class RingBuffer:
    """Fixed-capacity FIFO buffer.

    Single-writer (MQTT consumer task). Snapshots are safe to call from
    other coroutines on the same event loop — they return an immutable
    tuple copy.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._deque: deque[RingRecord] = deque(maxlen=capacity)

    def append(self, record: RingRecord) -> None:
        self._deque.append(record)

    def snapshot(self) -> tuple[RingRecord, ...]:
        return tuple(self._deque)

    def last(self) -> RingRecord | None:
        """Return the most-recently-appended record, or ``None`` if empty.

        O(1) peek — used by ``dispatch_and_fanout`` in ``service.py`` to
        hand the just-appended record to the hub without copying the whole
        deque. Do NOT compose this into a substitute for ``snapshot()``:
        the deque is shared with the consumer task, and iterating by
        repeatedly calling ``last()`` would race.
        """
        if not self._deque:
            return None
        return self._deque[-1]

    def extend(self, records: Iterable[RingRecord]) -> None:
        self._deque.extend(records)

    def __len__(self) -> int:
        return len(self._deque)
