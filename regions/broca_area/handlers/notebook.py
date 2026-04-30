"""Notebook handler for broca_area — STM recorder.

Listens broadly across broca's primary inputs (speech motor topics, habit
suggestions from basal_ganglia, directed cognitive requests) and records
a one-line summary of every envelope into ``memory.recent_events``. The
sleep coordinator later inspects that ring buffer to decide what to
consolidate.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the articulation pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the assoc_cortex / PFC notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/motor/speech/intent``,
notebook MUST use the wildcard ``hive/motor/speech/+`` (covering
``intent``, ``cancel``, ``complete``, plus future speech subtopics).
Same lesson Task 2 applied to PFC's motor topics.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Speech motor topics. Wildcard avoids exact-topic collision with
    # respond.py's ``hive/motor/speech/intent`` subscription. Catches
    # ``intent``, ``cancel``, ``complete``, and any future speech subtopic.
    "hive/motor/speech/+",
    # Basal ganglia habit suggestions — rehearsed phrasings broca may use.
    "hive/habit/suggestion",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/broca_area/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"motor.speech.intent"``.

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
