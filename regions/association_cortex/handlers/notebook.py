"""Notebook handler for association_cortex — STM recorder.

Listens broadly across sensory inputs, directed cognitive requests, and
external perception (chat/STT/captioning), and records a one-line summary
of every envelope into ``memory.recent_events``. The sleep coordinator
later inspects that ring buffer to decide what to consolidate.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the deliberation pass
lives in ``respond.py``.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Sensory: cover both 3-segment (hive/sensory/<modality>) and
    # 4-segment (hive/sensory/<modality>/<channel>) shapes. MQTT '+'
    # matches exactly one segment, so both filters are needed.
    "hive/sensory/+/+",
    "hive/sensory/+/+/+",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/association_cortex/+",
    # External perception — chat/STT/captioning thought-form text.
    # Wildcard rather than exact ``hive/external/perception`` so we don't
    # collide with respond.py (the loader rejects duplicate exact filters,
    # but allows overlapping wildcards) and so future external/* topics
    # are captured automatically.
    "hive/external/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"sensory.auditory.text"``.

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
