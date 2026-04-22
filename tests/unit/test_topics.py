"""Tests for shared.topics — canonical topic constants + wildcard matcher.

Covers spec §B.4 (lines 1396-1561 of the design doc).

Cases:
  test_no_duplicate_topics          — no two UPPER_SNAKE hive/ constants share a value
  test_topic_name_pattern           — all hive/ constants match the canonical regex
  test_topic_matches_exact          — exact match returns True
  test_topic_matches_plus_wildcard  — + matches exactly one segment
  test_topic_matches_hash_wildcard  — # matches zero or more trailing segments
  test_placeholder_fill             — fill() replaces {region} placeholders
  test_known_topics_present         — spot-check required constant names exist
"""
import re
import types

import pytest

from shared import topics
from shared.topics import (
    COGNITIVE_REGION_INBOX,
    MODULATOR_CORTISOL,
    SYSTEM_HEARTBEAT,
    TopicError,
    fill,
    topic_matches,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_hive_constants(mod: types.ModuleType) -> dict[str, str]:
    """Return {name: value} for all module-level UPPER_SNAKE_CASE string constants
    whose value starts with 'hive/'."""
    result = {}
    for name, value in vars(mod).items():
        if (
            isinstance(value, str)
            and value.startswith("hive/")
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        ):
            result[name] = value
    return result


# ---------------------------------------------------------------------------
# test_no_duplicate_topics
# ---------------------------------------------------------------------------

def test_no_duplicate_topics():
    """No two UPPER_SNAKE hive/ constants may share the same string value."""
    constants = _collect_hive_constants(topics)
    values = list(constants.values())
    assert len(set(values)) == len(values), (
        "Duplicate topic values found: "
        + str([v for v in values if values.count(v) > 1])
    )


# ---------------------------------------------------------------------------
# test_topic_name_pattern
# ---------------------------------------------------------------------------

# Allows lowercase letters, digits, underscores in segments, plus:
#   {region} placeholder, + and # wildcards
_TOPIC_PATTERN = re.compile(
    r"^hive/[a-z_]+(/[a-z0-9_+#{}]+)*$"
)


def test_topic_name_pattern():
    """All hive/ constants must match the canonical topic pattern."""
    constants = _collect_hive_constants(topics)
    bad = {name: val for name, val in constants.items()
           if not _TOPIC_PATTERN.fullmatch(val)}
    assert not bad, f"Constants with invalid topic patterns: {bad}"


# ---------------------------------------------------------------------------
# test_topic_matches_exact
# ---------------------------------------------------------------------------

def test_topic_matches_exact():
    assert topic_matches("hive/modulator/cortisol", "hive/modulator/cortisol") is True


def test_topic_matches_exact_no_cross():
    assert topic_matches("hive/modulator/cortisol", "hive/modulator/dopamine") is False


# ---------------------------------------------------------------------------
# test_topic_matches_plus_wildcard
# ---------------------------------------------------------------------------

def test_topic_matches_plus_wildcard_single_level_true():
    assert topic_matches("hive/system/heartbeat/+", "hive/system/heartbeat/amygdala") is True


def test_topic_matches_plus_wildcard_multi_level_false():
    """+ must NOT match multiple levels."""
    assert topic_matches(
        "hive/system/heartbeat/+",
        "hive/system/heartbeat/amygdala/extra",
    ) is False


def test_topic_matches_plus_wildcard_wrong_prefix_false():
    assert topic_matches("hive/system/heartbeat/+", "hive/system/sleep/amygdala") is False


def test_topic_matches_plus_wildcard_empty_extra_false():
    """Pattern with + and no topic match at that level."""
    assert topic_matches("hive/+/cortisol", "hive/modulator/cortisol") is True


# ---------------------------------------------------------------------------
# test_topic_matches_hash_wildcard
# ---------------------------------------------------------------------------

def test_topic_matches_hash_multi_level_true():
    assert topic_matches("hive/cognitive/#", "hive/cognitive/prefrontal/plan") is True


def test_topic_matches_hash_zero_extra_levels_true():
    """# matches zero trailing levels (the topic ends exactly at the parent)."""
    assert topic_matches("hive/cognitive/#", "hive/cognitive") is True


def test_topic_matches_hash_wrong_prefix_false():
    assert topic_matches("hive/cognitive/#", "hive/sensory/input/text") is False


def test_topic_matches_hash_not_terminal_false():
    """# appearing in non-terminal position should never match."""
    assert topic_matches("hive/#/plan", "hive/cognitive/plan") is False


def test_topic_matches_hash_single_extra_level_true():
    assert topic_matches("hive/cognitive/#", "hive/cognitive/thalamus") is True


# ---------------------------------------------------------------------------
# test_placeholder_fill
# ---------------------------------------------------------------------------

def test_placeholder_fill_heartbeat():
    result = fill(SYSTEM_HEARTBEAT, region="amygdala")
    assert result == "hive/system/heartbeat/amygdala"


def test_placeholder_fill_arbitrary_template():
    assert fill("hive/system/region_stats/{region}", region="vta") == "hive/system/region_stats/vta"


def test_placeholder_fill_cognitive_inbox():
    result = fill(COGNITIVE_REGION_INBOX, region="prefrontal_cortex")
    assert result == "hive/cognitive/prefrontal_cortex/#"


def test_placeholder_fill_missing_key_raises():
    with pytest.raises((TopicError, KeyError)):
        fill(SYSTEM_HEARTBEAT)  # missing region=


def test_placeholder_fill_no_placeholders():
    assert fill(MODULATOR_CORTISOL) == "hive/modulator/cortisol"


# ---------------------------------------------------------------------------
# test_known_topics_present
# ---------------------------------------------------------------------------

REQUIRED_CONSTANTS = [
    "SYSTEM_HEARTBEAT",
    "SYSTEM_SLEEP_REQUEST",
    "SYSTEM_SPAWN_REQUEST",
    "SYSTEM_SPAWN_PROPOSED",
    "MODULATOR_CORTISOL",
    "MODULATOR_DOPAMINE",
    "RHYTHM_GAMMA",
    "RHYTHM_BETA",
    "RHYTHM_THETA",
    "SELF_IDENTITY",
    "ATTENTION_FOCUS",
    "INTEROCEPTION_FELT_STATE",
    "HARDWARE_MIC",
    "HARDWARE_CAMERA",
    "HARDWARE_SPEAKER",
    "HARDWARE_MOTOR",
    "SENSORY_INPUT_TEXT",
    "COGNITIVE_THALAMUS_ATTEND",
    "COGNITIVE_PREFRONTAL_PLAN",
    "COGNITIVE_HIPPOCAMPUS_QUERY",
    "COGNITIVE_HIPPOCAMPUS_RESPONSE",
    "COGNITIVE_ASSOCIATION_INTEGRATE",
    "MOTOR_INTENT",
    "MOTOR_SPEECH_INTENT",
    "HABIT_SUGGESTION",
    "HABIT_REINFORCE",
    "HABIT_LEARNED",
    "BROADCAST_SHUTDOWN",
    "METACOGNITION_ERROR_DETECTED",
    "METACOGNITION_CONFLICT_OBSERVED",
    "METACOGNITION_REFLECTION_REQUEST",
    "METACOGNITION_REFLECTION_RESPONSE",
    "SYSTEM_REGION_STATS",
    "SYSTEM_METRICS_COMPUTE",
    "SYSTEM_METRICS_TOKENS",
    "SYSTEM_METRICS_REGION_HEALTH",
]


@pytest.mark.parametrize("name", REQUIRED_CONSTANTS)
def test_known_topics_present(name: str):
    assert hasattr(topics, name), f"shared.topics is missing constant: {name}"
    value = getattr(topics, name)
    assert isinstance(value, str), f"{name} should be a str, got {type(value)}"
    assert value.startswith("hive/"), f"{name} value should start with 'hive/', got {value!r}"
