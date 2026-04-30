"""Notebook handler for prefrontal_cortex — STM recorder.

Listens broadly across the topics PFC subscribes to (sensory streams,
motor outcomes, hippocampus retrievals, habit suggestions, directed
cognitive requests, external perception) and records a one-line summary
of every envelope into ``memory.recent_events``. The sleep coordinator
later inspects that ring buffer to decide what to consolidate.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the deliberation pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this expanded
subscription set ships in the same commit as the new respond.py and
the prompt revision. Pattern mirrors the association_cortex notebook
template (commit 878ec37 + review-fix 19e035a): MQTT '+' wildcard
matches exactly one segment, so 3-segment and 4-segment sensory shapes
each need their own filter.

The legacy ``hive/sensory/input/text`` subscription was dropped: no
publisher emits it (sensory cortexes use ``hive/sensory/auditory/text``,
``hive/sensory/visual/frames`` etc.), so the wildcards below replace it.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Hippocampus retrievals (PFC requests these and reads the response).
    "hive/cognitive/hippocampus/response",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/prefrontal_cortex/+",
    # External perception — chat/STT/captioning thought-form text.
    # Wildcard rather than exact ``hive/external/perception`` so future
    # external/* topics are captured automatically.
    "hive/external/+",
    # Motor outcomes — prediction-error feedback for executive learning.
    "hive/motor/complete",
    "hive/motor/failed",
    "hive/motor/partial",
    "hive/motor/speech/complete",
    # Basal ganglia habit suggestions.
    "hive/habit/suggestion",
    # Sensory: cover both 3-segment (hive/sensory/<modality>) and
    # 4-segment (hive/sensory/<modality>/<channel>) shapes. MQTT '+'
    # matches exactly one segment, so both filters are needed.
    "hive/sensory/+/+",
    "hive/sensory/+/+/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"motor.speech.complete"``.

    Drops the leading ``hive/`` segment and joins the remaining segments
    with dots. We cap at three trailing segments to keep the summary line
    bounded.
    """
    parts = topic.split("/")
    if parts and parts[0] == "hive":
        parts = parts[1:]
    return ".".join(parts[:3]) if parts else topic


def _extract_text(data: object) -> str:
    """Pull a printable string from envelope payload data."""
    if isinstance(data, dict):
        text = data.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        return text
    return str(data)


async def handle(envelope, ctx):
    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
