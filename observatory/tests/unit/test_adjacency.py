from observatory.adjacency import Adjacency


def test_records_rate_per_pair() -> None:
    adj = Adjacency(window_seconds=5.0)
    # t=0..4, three messages from A→B, one from A→C
    adj.record("A", ["B"], now=0.0)
    adj.record("A", ["B"], now=1.0)
    adj.record("A", ["B"], now=2.0)
    adj.record("A", ["C"], now=3.0)

    pairs = dict(((s, d), r) for s, d, r in adj.snapshot(now=4.0))
    # 3 msgs in 5s window → 0.6 msgs/sec
    assert round(pairs[("A", "B")], 2) == 0.60  # noqa: PLR2004
    assert round(pairs[("A", "C")], 2) == 0.20  # noqa: PLR2004


def test_old_events_fall_out_of_window() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", ["B"], now=0.0)
    adj.record("A", ["B"], now=1.0)
    # step forward past the window
    pairs = dict(((s, d), r) for s, d, r in adj.snapshot(now=10.0))
    assert pairs.get(("A", "B"), 0.0) == 0.0


def test_multiple_destinations_produce_multiple_edges() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", ["B", "C"], now=0.0)
    pairs = {(s, d) for s, d, _ in adj.snapshot(now=1.0)}
    assert pairs == {("A", "B"), ("A", "C")}


def test_no_destination_is_noop() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", [], now=0.0)
    assert adj.snapshot(now=1.0) == []
