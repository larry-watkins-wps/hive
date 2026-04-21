"""Per-client envelope drop logic.

V1 behavior: once a client exceeds ``max_rate`` envelopes in a 1 s window,
all further envelopes in that window are dropped. Priority-aware dropping
(heartbeat + rhythm first) is a v1.1 hook — the ``_LOW_PRIORITY_PREFIXES``
constant and ``_is_low_priority`` helper are retained below but intentionally
unused in v1, per the plan's comment anticipating future differentiation.
"""
from __future__ import annotations

# v1.1 hook — retained for future priority-aware drops (plan Step 7 comment).
_LOW_PRIORITY_PREFIXES = (
    "hive/system/heartbeat/",
    "hive/rhythm/",
)


def _is_low_priority(topic: str) -> bool:
    """v1.1 hook — not called in v1. Retained for priority-aware decimation."""
    return any(topic.startswith(p) for p in _LOW_PRIORITY_PREFIXES)


class Decimator:
    def __init__(self, max_rate: int) -> None:
        if max_rate <= 0:
            raise ValueError("max_rate must be positive")
        self._max = max_rate
        # `None` until the first call — avoids the phantom "window ending at
        # now=0.0" that would let callers with small `now` values accidentally
        # rotate on their first event.
        self._window_start: float | None = None
        self._kept_in_window: int = 0
        self._dropped_in_window: int = 0
        self._total_dropped: int = 0

    def _maybe_rotate(self, now: float) -> None:
        if self._window_start is None:
            self._window_start = now
            return
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._kept_in_window = 0
            self._dropped_in_window = 0

    def should_keep(self, record: dict, now: float) -> bool:
        self._maybe_rotate(now)
        if self._kept_in_window < self._max:
            self._kept_in_window += 1
            return True
        # Over budget. V1: drop unconditionally; count the drop.
        # (v1.1 will differentiate via _is_low_priority — see module docstring.)
        self._dropped_in_window += 1
        self._total_dropped += 1
        return False

    def drops_in_current_window(self) -> int:
        """Drops since the current 1 s window began.

        Resets to 0 on every window rotation. Use ``total_dropped`` for a
        cumulative counter.
        """
        return self._dropped_in_window

    def total_dropped(self) -> int:
        """Cumulative drops since the Decimator was constructed."""
        return self._total_dropped

    def drop_count(self) -> int:
        """Deprecated alias for :meth:`drops_in_current_window`.

        Retained so existing callers don't break; new code should call
        ``drops_in_current_window()`` or ``total_dropped()`` explicitly.
        """
        return self._dropped_in_window
