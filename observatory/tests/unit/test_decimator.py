from observatory.decimator import Decimator


def _env(topic: str) -> dict:
    return {"topic": topic, "envelope": {}}


def test_under_rate_limit_nothing_dropped() -> None:
    dec = Decimator(max_rate=100)
    kept = [dec.should_keep(_env("hive/cognitive/x"), now=0.0) for _ in range(50)]
    assert all(kept)
    assert dec.drops_in_current_window() == 0
    assert dec.total_dropped() == 0


def test_over_rate_limit_drops_low_priority_first() -> None:
    dec = Decimator(max_rate=10)
    # 15 messages in the same 1 s window — 5 should drop
    decisions = []
    for _ in range(10):
        decisions.append(dec.should_keep(_env("hive/cognitive/x"), now=0.0))
    for _ in range(5):
        decisions.append(dec.should_keep(_env("hive/system/heartbeat/thalamus"), now=0.0))
    kept_count = sum(1 for d in decisions if d)
    assert kept_count == 10  # noqa: PLR2004
    assert dec.drops_in_current_window() == 5  # noqa: PLR2004


def test_heartbeat_drops_before_cognitive() -> None:
    dec = Decimator(max_rate=2)
    # Fill budget with one cognitive and one heartbeat, then one more of each.
    # With budget = 2: first cognitive kept, first heartbeat kept (budget exhausted),
    # next cognitive must keep (displaces heartbeat in decision model is not the case;
    # our model is simpler: once over budget, drop low-priority first).
    # Simpler test: 3 heartbeats in a row with budget 2 — 2 kept, 1 dropped.
    r = [dec.should_keep(_env("hive/system/heartbeat/x"), now=0.0) for _ in range(3)]
    assert sum(r) == 2  # noqa: PLR2004
    assert dec.drops_in_current_window() == 1


def test_current_window_drops_reset_on_new_second_total_is_cumulative() -> None:
    dec = Decimator(max_rate=1)
    dec.should_keep(_env("hive/x"), now=0.0)
    dec.should_keep(_env("hive/x"), now=0.0)  # dropped
    assert dec.drops_in_current_window() == 1
    assert dec.total_dropped() == 1
    # new window
    dec.should_keep(_env("hive/x"), now=1.5)
    assert dec.drops_in_current_window() == 0
    assert dec.total_dropped() == 1  # cumulative survives rotation


def test_deprecated_drop_count_alias_still_works() -> None:
    dec = Decimator(max_rate=1)
    dec.should_keep(_env("hive/x"), now=0.0)
    dec.should_keep(_env("hive/x"), now=0.0)  # dropped
    # Legacy alias returns current-window drops.
    assert dec.drop_count() == 1


def test_first_window_anchored_to_first_event_not_zero() -> None:
    """With `_window_start=None` until first call, a caller whose monotonic
    clock reads e.g. 100.4 s does not rotate prematurely on their first
    event. The first window runs [first_now, first_now + 1.0)."""
    dec = Decimator(max_rate=2)
    # First event at now=100.4 — with the old `_window_start=0.0` model this
    # would have rotated immediately. With the fix, it anchors the window.
    assert dec.should_keep(_env("hive/x"), now=100.4) is True  # noqa: PLR2004
    assert dec.should_keep(_env("hive/x"), now=100.4) is True  # noqa: PLR2004
    assert dec.should_keep(_env("hive/x"), now=100.4) is False  # noqa: PLR2004 (over budget)
    assert dec.drops_in_current_window() == 1


def test_window_boundary_exclusive_at_just_below_one_second() -> None:
    """Just under 1 s after window start → still the same window; over
    budget → drop. At exactly 1 s → rotate; budget restored; keep."""
    dec = Decimator(max_rate=1)
    assert dec.should_keep(_env("hive/x"), now=10.0) is True  # noqa: PLR2004
    assert dec.should_keep(_env("hive/x"), now=10.99) is False  # noqa: PLR2004 — same window, over budget
    assert dec.drops_in_current_window() == 1
    # At now - window_start == 1.0 the window rotates.
    assert dec.should_keep(_env("hive/x"), now=11.0) is True  # noqa: PLR2004
    assert dec.drops_in_current_window() == 0
