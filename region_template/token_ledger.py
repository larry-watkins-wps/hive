"""Token ledger — rolling-window accounting with reservations (spec §C.11).

The ledger tracks LLM token usage and USD cost across rolling time windows
and tentative pre-call reservations. Two reasons it lives here (not in the
adapter):

1. The adapter reserves an estimate before calling the provider, then records
   the actual usage afterward. :meth:`over_budget` must account for both.
2. ``TokenUsage`` is ledger data; keeping it here avoids a circular import
   between ``token_ledger.py`` and ``llm_adapter.py``.

Units
-----

- Token counts are ints.
- USD cost is stored internally in **micro-USD** (cost_usd * 1_000_000) so the
  ``RollingWindow`` can keep pure-int math; :meth:`effective_usage` converts
  back to USD when returning values.

Soft vs hard budget
-------------------

:meth:`over_warning_threshold` returns the name of any bucket that is at or
above 80 % of its budget (but still under 100 %) — the adapter logs WARN and
publishes a metacog warning, but the call proceeds.

:meth:`over_budget` returns the name of any bucket strictly over 100 % — the
adapter raises ``LlmError("over_budget", retryable=False)`` and never calls
the provider.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from region_template.config_loader import LlmBudgets

__all__ = [
    "EffectiveUsage",
    "RollingWindow",
    "TokenLedger",
    "TokenUsage",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    """Per-call LLM usage figures extracted from the provider response.

    ``cache_read_tokens`` is what Anthropic / OpenAI bill at the cheaper
    cached rate. ``cache_write_tokens`` is the one-time cost to seed the
    cache (Anthropic only).
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class EffectiveUsage:
    """Rolling-window totals plus any outstanding reservations.

    ``input_hour`` sums ``_hourly_in`` (actual, cache-discounted) plus all
    pending reservations — so a burst of pre-reserves can't hide from
    :meth:`over_budget`.
    """

    input_hour: int
    output_hour: int
    cost_day_usd: float


# ---------------------------------------------------------------------------
# RollingWindow — fixed-duration sliding sum
# ---------------------------------------------------------------------------


@dataclass
class RollingWindow:
    """Fixed-duration sliding-sum accumulator keyed on wall time.

    ``samples`` is a deque of ``(ts, tokens)`` pairs sorted by insertion order
    (effectively by ts since callers always pass ``time.time()``). :meth:`sum`
    prunes entries older than ``window_s`` before returning the remaining
    total, keeping the deque bounded to the active window.
    """

    window_s: int
    samples: deque[tuple[float, int]] = field(default_factory=deque)

    def add(self, tokens: int, ts: float | None = None) -> None:
        """Append ``tokens`` observed at ``ts`` (default: now).

        Zero and negative deltas are recorded faithfully — callers that want
        to clamp should do so upstream.
        """
        if ts is None:
            ts = time.time()
        self.samples.append((ts, tokens))

    def sum(self, now: float | None = None) -> int:
        """Return the total tokens in the window, pruning stale entries.

        Entries older than ``now - window_s`` are evicted from the left of
        the deque. The return value is always an int (micro-USD included).
        """
        if now is None:
            now = time.time()
        cutoff = now - self.window_s
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        return sum(tokens for _, tokens in self.samples)


# ---------------------------------------------------------------------------
# TokenLedger — public API
# ---------------------------------------------------------------------------

_WARN_FRACTION = 0.8

# Names of the three budget buckets the ledger tracks. Aliased here so the
# return types of `over_budget` and `over_warning_threshold` can share.
BucketName = Literal["per_hour_input", "per_hour_output", "per_day_cost"]


class TokenLedger:
    """Rolling-window token + cost accounting with pre-call reservations.

    One instance per region. Not thread-safe; callers running the adapter
    from a single asyncio event loop don't need locking (all mutations happen
    on the loop thread).
    """

    def __init__(self, budgets: LlmBudgets) -> None:
        self._budgets = budgets
        self._hourly_in = RollingWindow(3600)
        self._hourly_out = RollingWindow(3600)
        # Stored in micro-USD so the window keeps int math.
        self._daily_cost_micro_usd = RollingWindow(86400)
        # handle (uuid4 hex) -> reserved-token estimate
        self._reservations: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Reservation lifecycle
    # ------------------------------------------------------------------

    def reserve(self, estimate: int) -> str:
        """Record an ``estimate`` token pre-reservation.

        Returns a uuid4-hex handle. The caller must pass this handle to
        :meth:`record` on success, or to :meth:`release` on failure. An
        unreleased reservation inflates :meth:`effective_usage` until its
        owner cleans it up.
        """
        handle = uuid.uuid4().hex
        self._reservations[handle] = estimate
        return handle

    def record(self, handle: str, usage: TokenUsage, cost_usd: float) -> None:
        """Convert a reservation into real usage.

        Adds ``usage.input_tokens - usage.cache_read_tokens`` (the *billed*
        input count per §C.11) to the hourly-input window, ``output_tokens``
        to the hourly-output window, and ``cost_usd`` (in micro-USD) to the
        daily-cost window. Drops the reservation silently if the handle is
        unknown — callers are free to record without a prior reservation.
        """
        self._reservations.pop(handle, None)
        now = time.time()
        billed_in = max(0, usage.input_tokens - usage.cache_read_tokens)
        self._hourly_in.add(billed_in, now)
        self._hourly_out.add(usage.output_tokens, now)
        self._daily_cost_micro_usd.add(int(cost_usd * 1_000_000), now)

    def release(self, handle: str) -> None:
        """Drop an unused reservation (e.g. after a failed provider call)."""
        self._reservations.pop(handle, None)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def effective_usage(self) -> EffectiveUsage:
        """Return current rolling-window usage, counting active reservations.

        Reservations are added to ``input_hour`` only. A pending reservation
        that over-estimates input will be corrected by :meth:`record`
        replacing the reservation with the real count.
        """
        reserved_in = sum(self._reservations.values())
        return EffectiveUsage(
            input_hour=self._hourly_in.sum() + reserved_in,
            output_hour=self._hourly_out.sum(),
            cost_day_usd=self._daily_cost_micro_usd.sum() / 1_000_000,
        )

    def over_budget(self) -> BucketName | None:
        """Return the first bucket strictly over budget, or ``None``."""
        u = self.effective_usage()
        if u.input_hour > self._budgets.per_hour_input_tokens:
            return "per_hour_input"
        if u.output_hour > self._budgets.per_hour_output_tokens:
            return "per_hour_output"
        if u.cost_day_usd > self._budgets.per_day_cost_usd:
            return "per_day_cost"
        return None

    def over_warning_threshold(self) -> BucketName | None:
        """Return the first bucket >=80% but not yet strictly over budget."""
        u = self.effective_usage()
        if (
            u.input_hour >= self._budgets.per_hour_input_tokens * _WARN_FRACTION
            and u.input_hour <= self._budgets.per_hour_input_tokens
        ):
            return "per_hour_input"
        if (
            u.output_hour >= self._budgets.per_hour_output_tokens * _WARN_FRACTION
            and u.output_hour <= self._budgets.per_hour_output_tokens
        ):
            return "per_hour_output"
        if (
            u.cost_day_usd >= self._budgets.per_day_cost_usd * _WARN_FRACTION
            and u.cost_day_usd <= self._budgets.per_day_cost_usd
        ):
            return "per_day_cost"
        return None
