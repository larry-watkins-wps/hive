"""Rolling message-rate matrix per (source, destination) pair."""
from __future__ import annotations

from collections import defaultdict, deque


class Adjacency:
    # Baseline window: pairs observed in the last N seconds count as "alive"
    # for the always-on topology web. Longer than the 5 s rate window so the
    # baseline feels stable between bursts; short enough that a pair that
    # stops firing eventually fades out of the frontend's edge set, so the
    # viz shows recent connectivity rather than every pair ever seen.
    _BASELINE_WINDOW_S = 30.0

    def __init__(self, window_seconds: float = 5.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        # Undirected canonical pairs (alphabetical) → last-seen timestamp.
        # Replaces the previous append-only ``_ever_seen`` set; `recent_pairs`
        # filters on the baseline window so idle pairs fall out of the
        # frontend's rendered edge set.
        self._last_seen: dict[tuple[str, str], float] = {}

    def record(self, source: str, destinations: list[str], now: float) -> None:
        for dst in destinations:
            self._events[(source, dst)].append(now)
            # Canonicalise undirected so (A,B) and (B,A) collapse. Region
            # names are `^[A-Za-z0-9_-]+$` so alphabetic sort is stable.
            pair = (source, dst) if source < dst else (dst, source)
            self._last_seen[pair] = now

    def recent_pairs(self, now: float) -> list[tuple[str, str]]:
        """Undirected pairs observed within the baseline window.

        Replaces ``ever_seen_pairs``: instead of growing forever, pairs that
        haven't fired in ``_BASELINE_WINDOW_S`` drop out. The frontend uses
        this as the always-on baseline, so the edge set reflects current
        topology rather than historical accumulation.
        """
        cutoff = now - self._BASELINE_WINDOW_S
        stale = [p for p, t in self._last_seen.items() if t < cutoff]
        for p in stale:
            del self._last_seen[p]
        return sorted(self._last_seen.keys())

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        for pair, events in list(self._events.items()):
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                del self._events[pair]

    def snapshot(self, now: float) -> list[tuple[str, str, float]]:
        """Return ``[(src, dst, mean_msgs_per_second_over_window), ...]``.

        The third tuple element is the mean rate over the full window
        (``len(events_in_window) / window_seconds``), not an instantaneous
        rate. Consumers expecting smooth edge-thickness values want this;
        a burst-detector would need a separate shorter window.
        """
        self._evict(now)
        return [
            (src, dst, len(events) / self._window)
            for (src, dst), events in self._events.items()
        ]
