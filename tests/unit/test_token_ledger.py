"""Tests for :mod:`region_template.token_ledger` — spec §C.11.

Covers:

- ``RollingWindow.add`` / ``RollingWindow.sum`` prune stale entries.
- ``TokenLedger.reserve`` contributes to ``effective_usage.input_hour``.
- ``TokenLedger.record`` subtracts ``cache_read_tokens`` from billed input.
- ``TokenLedger.record`` clears the matching reservation.
- ``TokenLedger.over_budget`` trips when a bucket goes over.
- ``TokenLedger.over_warning_threshold`` trips at 80%.
"""
from __future__ import annotations

from region_template.config_loader import LlmBudgets
from region_template.token_ledger import (
    EffectiveUsage,
    RollingWindow,
    TokenLedger,
    TokenUsage,
)

# Named constants keep ruff PLR2004 quiet.
_WINDOW_S = 3600
_SMALL_CAP = 1_000
_MED_CAP = 10_000
_SUM_100_PLUS_50 = 150
_SUM_50_ONLY = 50
_SUM_100_MINUS_30 = 70
_RESERVE_500 = 500
_BILLED_INPUT_300 = 300  # 400 - 100 cache read
_OUTPUT_200 = 200
_COST_TOLERANCE = 1e-6
_RECORD_100 = 100
_RECORD_50 = 50


# ---------------------------------------------------------------------------
# RollingWindow
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_add_then_sum_returns_total(self) -> None:
        w = RollingWindow(_WINDOW_S)
        w.add(100, ts=1000.0)
        w.add(50, ts=1010.0)
        assert w.sum(now=1020.0) == _SUM_100_PLUS_50

    def test_sum_prunes_entries_older_than_window(self) -> None:
        w = RollingWindow(_WINDOW_S)
        w.add(100, ts=1000.0)
        w.add(50, ts=1000.0 + _WINDOW_S + 10)  # way past the window
        # At now=ts=1000+WINDOW+20, first sample is stale (older than cutoff).
        assert w.sum(now=1000.0 + _WINDOW_S + 20) == _SUM_50_ONLY

    def test_sum_with_all_stale_returns_zero(self) -> None:
        w = RollingWindow(_WINDOW_S)
        w.add(77, ts=100.0)
        assert w.sum(now=100.0 + _WINDOW_S + 1) == 0

    def test_add_negative_tokens_is_recorded(self) -> None:
        """RollingWindow is honest about whatever callers give it."""
        w = RollingWindow(_WINDOW_S)
        w.add(100, ts=1.0)
        w.add(-30, ts=2.0)
        assert w.sum(now=3.0) == _SUM_100_MINUS_30


# ---------------------------------------------------------------------------
# TokenLedger — reservations + record
# ---------------------------------------------------------------------------


def _budgets(
    per_hour_input: int = _MED_CAP,
    per_hour_output: int = _MED_CAP,
    per_day_cost_usd: float = 10.0,
) -> LlmBudgets:
    return LlmBudgets(
        per_call_max_tokens=2048,
        per_hour_input_tokens=per_hour_input,
        per_hour_output_tokens=per_hour_output,
        per_day_cost_usd=per_day_cost_usd,
    )


class TestReservation:
    def test_reserve_returns_unique_handle(self) -> None:
        ledger = TokenLedger(_budgets())
        h1 = ledger.reserve(100)
        h2 = ledger.reserve(100)
        assert h1 != h2

    def test_reserve_contributes_to_input_hour(self) -> None:
        ledger = TokenLedger(_budgets())
        ledger.reserve(_RESERVE_500)
        u = ledger.effective_usage()
        assert u.input_hour == _RESERVE_500
        assert u.output_hour == 0
        assert u.cost_day_usd == 0.0

    def test_release_clears_reservation(self) -> None:
        ledger = TokenLedger(_budgets())
        h = ledger.reserve(_RESERVE_500)
        ledger.release(h)
        assert ledger.effective_usage().input_hour == 0

    def test_release_unknown_handle_is_noop(self) -> None:
        ledger = TokenLedger(_budgets())
        ledger.release("not-a-real-handle")  # must not raise


class TestRecord:
    def test_record_clears_reservation_and_adds_actuals(self) -> None:
        ledger = TokenLedger(_budgets())
        h = ledger.reserve(_RESERVE_500)
        usage = TokenUsage(
            input_tokens=400,
            output_tokens=_OUTPUT_200,
            cache_read_tokens=100,
            cache_write_tokens=0,
        )
        ledger.record(h, usage, cost_usd=0.05)
        u = ledger.effective_usage()
        # billed input = input - cache_read = 300
        assert u.input_hour == _BILLED_INPUT_300
        assert u.output_hour == _OUTPUT_200
        # Cost round-tripped through micro-USD — floating-point tolerance OK.
        assert abs(u.cost_day_usd - 0.05) < _COST_TOLERANCE

    def test_record_without_prior_reservation_is_accepted(self) -> None:
        ledger = TokenLedger(_budgets())
        usage = TokenUsage(
            input_tokens=_RECORD_100,
            output_tokens=_RECORD_50,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
        ledger.record("unknown-handle", usage, cost_usd=0.01)
        u = ledger.effective_usage()
        assert u.input_hour == _RECORD_100
        assert u.output_hour == _RECORD_50

    def test_record_clamps_negative_billed_input_to_zero(self) -> None:
        """cache_read > input_tokens should not roll the ledger backwards."""
        ledger = TokenLedger(_budgets())
        usage = TokenUsage(
            input_tokens=50,
            output_tokens=0,
            cache_read_tokens=999,
            cache_write_tokens=0,
        )
        ledger.record("h", usage, cost_usd=0.0)
        assert ledger.effective_usage().input_hour == 0


# ---------------------------------------------------------------------------
# over_budget + warning threshold
# ---------------------------------------------------------------------------


class TestOverBudget:
    def test_under_budget_returns_none(self) -> None:
        ledger = TokenLedger(_budgets(per_hour_input=10_000))
        ledger.reserve(100)
        assert ledger.over_budget() is None

    def test_input_bucket_over_returns_per_hour_input(self) -> None:
        ledger = TokenLedger(_budgets(per_hour_input=1000))
        ledger.reserve(1001)
        assert ledger.over_budget() == "per_hour_input"

    def test_output_bucket_over_returns_per_hour_output(self) -> None:
        ledger = TokenLedger(_budgets(per_hour_output=1000))
        ledger.record(
            "h",
            TokenUsage(
                input_tokens=0,
                output_tokens=1001,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            cost_usd=0.0,
        )
        assert ledger.over_budget() == "per_hour_output"

    def test_cost_bucket_over_returns_per_day_cost(self) -> None:
        ledger = TokenLedger(_budgets(per_day_cost_usd=1.0))
        ledger.record(
            "h",
            TokenUsage(
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
            cost_usd=1.5,
        )
        assert ledger.over_budget() == "per_day_cost"


class TestWarningThreshold:
    def test_below_80_percent_returns_none(self) -> None:
        ledger = TokenLedger(_budgets(per_hour_input=1000))
        ledger.reserve(700)
        assert ledger.over_warning_threshold() is None

    def test_at_or_above_80_percent_returns_bucket(self) -> None:
        ledger = TokenLedger(_budgets(per_hour_input=1000))
        ledger.reserve(800)
        assert ledger.over_warning_threshold() == "per_hour_input"

    def test_at_100_percent_still_warning(self) -> None:
        """At exactly the cap we warn but don't hard-reject."""
        ledger = TokenLedger(_budgets(per_hour_input=1000))
        ledger.reserve(1000)
        assert ledger.over_warning_threshold() == "per_hour_input"
        assert ledger.over_budget() is None

    def test_strictly_over_cap_no_longer_warning(self) -> None:
        """Strictly over the cap is a hard reject; warning only applies ≤ 100%."""
        ledger = TokenLedger(_budgets(per_hour_input=1000))
        ledger.reserve(1001)
        assert ledger.over_warning_threshold() is None
        assert ledger.over_budget() == "per_hour_input"


# ---------------------------------------------------------------------------
# effective_usage type
# ---------------------------------------------------------------------------


def test_effective_usage_is_immutable_dataclass() -> None:
    ledger = TokenLedger(_budgets())
    u = ledger.effective_usage()
    assert isinstance(u, EffectiveUsage)
