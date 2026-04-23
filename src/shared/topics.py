"""Canonical Hive MQTT topic constants (spec §B.4).

This module is the single Python-side source of truth for topic names.
Constants use UPPER_SNAKE_CASE. Topics with region-specific segments use
`{region}` placeholders; fill them via `fill(template, region=...)`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Hardware (ACL-gated; raw bytes, NOT envelope)
# ---------------------------------------------------------------------------
HARDWARE_MIC = "hive/hardware/mic"
HARDWARE_CAMERA = "hive/hardware/camera"
HARDWARE_SPEAKER = "hive/hardware/speaker"
HARDWARE_MOTOR = "hive/hardware/motor"

# ---------------------------------------------------------------------------
# Sensory (processed, broadcast-safe)
# ---------------------------------------------------------------------------
SENSORY_VISUAL_PROCESSED = "hive/sensory/visual/processed"
SENSORY_VISUAL_FEATURES = "hive/sensory/visual/features"
SENSORY_AUDITORY_TEXT = "hive/sensory/auditory/text"
SENSORY_AUDITORY_FEATURES = "hive/sensory/auditory/features"
SENSORY_AUDITORY_EVENTS = "hive/sensory/auditory/events"
SENSORY_INPUT_TEXT = "hive/sensory/input/text"

# ---------------------------------------------------------------------------
# Cognitive — inter-region messaging
# ---------------------------------------------------------------------------
COGNITIVE_THALAMUS_ATTEND = "hive/cognitive/thalamus/attend"
COGNITIVE_PREFRONTAL_PLAN = "hive/cognitive/prefrontal/plan"
COGNITIVE_HIPPOCAMPUS_QUERY = "hive/cognitive/hippocampus/query"
COGNITIVE_HIPPOCAMPUS_RESPONSE = "hive/cognitive/hippocampus/response"
COGNITIVE_ASSOCIATION_INTEGRATE = "hive/cognitive/association/integrate"
COGNITIVE_REGION_INBOX = "hive/cognitive/{region}/#"  # wildcard inbox pattern per region

# ---------------------------------------------------------------------------
# Motor — pre-hardware intents
# ---------------------------------------------------------------------------
MOTOR_INTENT = "hive/motor/intent"
MOTOR_INTENT_CANCEL = "hive/motor/intent/cancel"
MOTOR_SPEECH_INTENT = "hive/motor/speech/intent"
MOTOR_SPEECH_CANCEL = "hive/motor/speech/cancel"
MOTOR_SPEECH_COMPLETE = "hive/motor/speech/complete"
MOTOR_COMPLETE = "hive/motor/complete"
MOTOR_FAILED = "hive/motor/failed"
MOTOR_PARTIAL = "hive/motor/partial"

# ---------------------------------------------------------------------------
# System — framework/infrastructure
# ---------------------------------------------------------------------------
SYSTEM_HEARTBEAT = "hive/system/heartbeat/{region}"
SYSTEM_HEARTBEAT_WILDCARD = "hive/system/heartbeat/+"
SYSTEM_SLEEP_REQUEST = "hive/system/sleep/request"
SYSTEM_SLEEP_GRANTED = "hive/system/sleep/granted"
SYSTEM_SLEEP_FORCE = "hive/system/sleep/force"
SYSTEM_RESTART_REQUEST = "hive/system/restart/request"
SYSTEM_SPAWN_PROPOSED = "hive/system/spawn/proposed"
SYSTEM_SPAWN_REQUEST = "hive/system/spawn/request"
SYSTEM_SPAWN_COMPLETE = "hive/system/spawn/complete"
SYSTEM_SPAWN_FAILED = "hive/system/spawn/failed"
SYSTEM_SPAWN_QUERY = "hive/system/spawn/query"
SYSTEM_SPAWN_QUERY_RESPONSE = "hive/system/spawn/query_response"
SYSTEM_CODECHANGE_PROPOSED = "hive/system/codechange/proposed"
SYSTEM_CODECHANGE_APPROVED = "hive/system/codechange/approved"
SYSTEM_METRICS_COMPUTE = "hive/system/metrics/compute"
SYSTEM_METRICS_TOKENS = "hive/system/metrics/tokens"
SYSTEM_METRICS_REGION_HEALTH = "hive/system/metrics/region_health"
SYSTEM_REGION_STATS = "hive/system/region_stats/{region}"
SYSTEM_REGION_STATS_WILDCARD = "hive/system/region_stats/+"

# ---------------------------------------------------------------------------
# Metacognition — ACC channels
# ---------------------------------------------------------------------------
METACOGNITION_ERROR_DETECTED = "hive/metacognition/error/detected"
METACOGNITION_CONFLICT_OBSERVED = "hive/metacognition/conflict/observed"
METACOGNITION_REFLECTION_REQUEST = "hive/metacognition/reflection/request"
METACOGNITION_REFLECTION_RESPONSE = "hive/metacognition/reflection/response"

# ---------------------------------------------------------------------------
# Attention (retained)
# ---------------------------------------------------------------------------
ATTENTION_FOCUS = "hive/attention/focus"
ATTENTION_SALIENCE = "hive/attention/salience"

# ---------------------------------------------------------------------------
# Self (retained — mPFC only publishes)
# ---------------------------------------------------------------------------
SELF_IDENTITY = "hive/self/identity"
SELF_VALUES = "hive/self/values"
SELF_PERSONALITY = "hive/self/personality"
SELF_AUTOBIOGRAPHICAL_INDEX = "hive/self/autobiographical_index"

# ---------------------------------------------------------------------------
# Interoception (retained — insula publishes)
# ---------------------------------------------------------------------------
INTEROCEPTION_COMPUTE_LOAD = "hive/interoception/compute_load"
INTEROCEPTION_TOKEN_BUDGET = "hive/interoception/token_budget"
INTEROCEPTION_REGION_HEALTH = "hive/interoception/region_health"
INTEROCEPTION_FELT_STATE = "hive/interoception/felt_state"

# ---------------------------------------------------------------------------
# Habit
# ---------------------------------------------------------------------------
HABIT_SUGGESTION = "hive/habit/suggestion"
HABIT_REINFORCE = "hive/habit/reinforce"
HABIT_LEARNED = "hive/habit/learned"

# ---------------------------------------------------------------------------
# Modulator — ambient chemical fields (all retained)
# ---------------------------------------------------------------------------
MODULATOR_DOPAMINE = "hive/modulator/dopamine"
MODULATOR_CORTISOL = "hive/modulator/cortisol"
MODULATOR_NOREPINEPHRINE = "hive/modulator/norepinephrine"
MODULATOR_SEROTONIN = "hive/modulator/serotonin"
MODULATOR_ACETYLCHOLINE = "hive/modulator/acetylcholine"
MODULATOR_OXYTOCIN = "hive/modulator/oxytocin"

# ---------------------------------------------------------------------------
# Rhythm — oscillatory timing (not retained; broadcast)
# ---------------------------------------------------------------------------
RHYTHM_GAMMA = "hive/rhythm/gamma"
RHYTHM_BETA = "hive/rhythm/beta"
RHYTHM_THETA = "hive/rhythm/theta"

# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------
BROADCAST_SHUTDOWN = "hive/broadcast/shutdown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TopicError(Exception):
    """Raised when topic helpers encounter malformed input."""


def fill(template: str, **kwargs: str) -> str:
    """Fill {placeholder} segments in a topic template.

    Raises TopicError if any placeholder required by the template is missing
    from kwargs, or if the filled result contains empty segments.
    """
    try:
        result = template.format(**kwargs)
    except KeyError as e:
        raise TopicError(f"missing placeholder {e} for template {template!r}") from e
    if "//" in result or result.startswith("/") or result.endswith("/"):
        raise TopicError(f"filled template produced malformed topic: {result!r}")
    return result


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT-style topic match. `+` = one level; `#` = zero or more trailing levels.

    `#` MUST be the final segment of the pattern, otherwise always returns False.
    `+` may appear at any single level. Matching is case-sensitive and exact
    outside of wildcards.

    Edge cases:
    - `#` at the terminal position of pattern matches zero additional levels,
      meaning the topic may end at the parent segment before the `#`.
    - A pattern containing `#` in a non-terminal position never matches.
    """
    p_parts = pattern.split("/")
    t_parts = topic.split("/")

    for i, p in enumerate(p_parts):
        if p == "#":
            # Must be terminal in pattern; matches any remaining levels (including zero)
            return i == len(p_parts) - 1
        if i >= len(t_parts):
            return False
        if p == "+":
            continue
        if p != t_parts[i]:
            return False

    return len(p_parts) == len(t_parts)
