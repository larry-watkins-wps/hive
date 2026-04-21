"""Rolling message-rate matrix per (source, destination) pair."""
from __future__ import annotations

from collections import defaultdict, deque


class Adjacency:
    def __init__(self, window_seconds: float = 5.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def record(self, source: str, destinations: list[str], now: float) -> None:
        for dst in destinations:
            self._events[(source, dst)].append(now)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        for pair, events in list(self._events.items()):
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                del self._events[pair]

    def snapshot(self, now: float) -> list[tuple[str, str, float]]:
        self._evict(now)
        return [
            (src, dst, len(events) / self._window)
            for (src, dst), events in self._events.items()
        ]
