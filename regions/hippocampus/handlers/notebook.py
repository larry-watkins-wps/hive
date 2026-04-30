"""Notebook handler for hippocampus — STM recorder.

Hippocampus is the keeper of episodic memory. Its notebook listens
broadly across the topics hippocampus subscribes to (cognitive
requests/responses directed at hippocampus, sensory streams, integration
syntheses, metacognition reflections, spawn proposals, external
perception) and records a one-line summary of every envelope into
``memory.recent_events``. The sleep coordinator later inspects that
ring buffer to decide what to consolidate into LTM.

This handler does not call the LLM and does not publish. It is the
cheap "this happened during wake" pen-and-paper pass; the encoding /
query-response pass lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this expanded
subscription set ships in the same commit as the new respond.py and
the prompt revision. Pattern mirrors the assoc_cortex / PFC / broca
notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/cognitive/hippocampus/
query``, notebook MUST use the wildcard ``hive/cognitive/hippocampus/+``
(covering ``query``, ``response``, ``episode``, ``encoded``,
``encoding_hint``, plus future hippocampus subtopics). Same lesson
Tasks 2 and 3 applied.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Hippocampus-directed traffic. Wildcard avoids exact-topic collision
    # with respond.py's ``hive/cognitive/hippocampus/query`` subscription.
    # Catches ``query``, ``response``, ``episode``, ``encoded``,
    # ``encoding_hint``, and any future hippocampus subtopic.
    "hive/cognitive/hippocampus/+",
    # External perception — chat/STT/captioning thought-form text. The
    # primary stream of episodic candidates from outside Hive. Wildcard
    # rather than exact ``hive/external/perception`` so future external/*
    # topics are captured automatically.
    "hive/external/+",
    # Sensory: cover both 3-segment (hive/sensory/<modality>) and
    # 4-segment (hive/sensory/<modality>/<channel>) shapes. MQTT '+'
    # matches exactly one segment, so both filters are needed.
    "hive/sensory/+/+",
    "hive/sensory/+/+/+",
    # Cognitive integration outputs from all cognitive regions —
    # synthesis envelopes are prime candidates for episodic encoding.
    "hive/cognitive/+/integration",
    # Metacognition reflection responses — important episodes to record.
    "hive/metacognition/reflection/response",
    # Spawn proposals — system-level events worth remembering.
    "hive/system/spawn/proposed",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"external.perception"``.

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
