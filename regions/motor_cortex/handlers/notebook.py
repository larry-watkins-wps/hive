"""Notebook handler for motor_cortex — STM recorder.

Listens broadly across motor_cortex's primary inputs (motor topics, habit
suggestions from basal_ganglia, directed cognitive requests) and records
a one-line summary of every envelope into ``memory.recent_events``. The
sleep coordinator later inspects that ring buffer to decide what to
consolidate.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the execution pass lives
in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the broca / assoc_cortex / PFC notebook
templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/motor/intent``, notebook
MUST use the wildcards ``hive/motor/+`` (3-segment: catches ``intent``,
``complete``, ``failed``, ``partial``) and ``hive/motor/+/+`` (4-segment:
catches ``intent/cancel``).

Self-receive filter (NEW for motor_cortex): motor_cortex publishes
``hive/motor/{complete,failed,partial}`` from its own respond handler.
Without a filter, those self-publishes would feed back into STM via the
``hive/motor/+`` wildcard subscription — biologically odd and inflates
the deliberation context. The handler early-returns when
``envelope.source_region == ctx.region_name``.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Motor topics, 3-segment. Wildcard avoids exact-topic collision with
    # respond.py's ``hive/motor/intent`` subscription. Catches ``intent``,
    # ``complete``, ``failed``, ``partial``, and any future 3-segment
    # motor subtopic.
    "hive/motor/+",
    # Motor topics, 4-segment. Catches ``intent/cancel`` and any future
    # 4-segment motor subtopic.
    "hive/motor/+/+",
    # Basal ganglia habit suggestions — rehearsed actions motor_cortex
    # may execute.
    "hive/habit/suggestion",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/motor_cortex/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"motor.intent"`` or ``"motor.intent.cancel"``.

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
        # Prefer ``action`` (motor intents), fall back to ``text``,
        # then stringify the whole dict.
        for key in ("action", "text", "phrase", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # motor_cortex publishes ``motor/{complete,failed,partial}`` which
    # would otherwise feed back into STM via the ``hive/motor/+``
    # wildcard.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
