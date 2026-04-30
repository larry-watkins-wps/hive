"""Notebook handler for basal_ganglia — STM recorder.

Listens broadly across basal_ganglia's primary inputs (sensory streams
that supply context for action selection, directed cognitive requests,
and the full habit/* surface) and records a one-line summary of every
envelope into ``memory.recent_events``. The sleep coordinator later
inspects that ring buffer to decide what to consolidate, and the
``respond.py`` action-select handler reads it as gating context.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the deliberation pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the motor_cortex / broca / assoc_cortex / PFC
notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. notebook
uses only wildcard patterns; respond's subscriptions are also wildcards
(``hive/cognitive/+/integration`` and the exact
``hive/cognitive/prefrontal_cortex/plan`` — neither collides with
notebook's ``hive/cognitive/basal_ganglia/+`` since the second-segment
strings differ).

Self-receive filter (NEW for action-selection regions): basal_ganglia
publishes ``hive/habit/{suggestion,reinforce,learned,extinguished}`` from
its respond / future habit-counter handlers. Without a filter those
self-publishes would feed back into STM via the ``hive/habit/+``
wildcard subscription — biologically odd and inflates the gating
context. The handler early-returns when
``envelope.source_region == ctx.region_name``.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Sensory streams, 3-segment. Catches ``auditory/text``, ``visual/scene``,
    # etc. Action selection needs to know what the world is presenting.
    "hive/sensory/+/+",
    # Sensory streams, 4-segment. Catches future deeper-namespaced sensory
    # subtopics without a respond.py override needed.
    "hive/sensory/+/+/+",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/basal_ganglia/+",
    # Full habit topic surface — wildcard catches reinforce + suggestion +
    # learned + extinguished plus any future habit subtopic.
    "hive/habit/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"sensory.auditory.text"`` or ``"habit.reinforce"``.

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
        # Prefer fields that carry a meaningful one-liner. ``action`` for
        # motor-shaped payloads, ``text``/``phrase`` for speech and habit
        # suggestions, ``reason`` for cancels, ``summary`` for integration
        # outputs that occasionally land on cognitive/basal_ganglia/*.
        for key in ("action", "text", "phrase", "summary", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # basal_ganglia publishes ``habit/{suggestion,reinforce,learned,
    # extinguished}`` which would otherwise feed back into STM via the
    # ``hive/habit/+`` wildcard.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
