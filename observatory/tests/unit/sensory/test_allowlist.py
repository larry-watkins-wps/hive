"""Allowlist is the spec §4.2 boundary: exactly one topic for v4."""
from observatory.sensory.allowlist import ALLOWED_PUBLISH_TOPICS


def test_v4_allowlist_is_exactly_one_topic() -> None:
    """Spec §4.2: 'v4 = `hive/external/perception` only.'"""
    assert frozenset({"hive/external/perception"}) == ALLOWED_PUBLISH_TOPICS


def test_allowlist_is_immutable() -> None:
    """Frozenset prevents accidental in-flight mutation by routes/tests."""
    assert isinstance(ALLOWED_PUBLISH_TOPICS, frozenset)
