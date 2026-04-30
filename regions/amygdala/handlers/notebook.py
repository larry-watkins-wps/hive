"""Notebook handler for amygdala — STM recorder.

Listens broadly across amygdala's primary inputs (sensory features and
events, hippocampal memory responses, external perception) and records a
one-line summary of every envelope into ``memory.recent_events``. The
sleep coordinator later inspects that ring buffer to decide what to
consolidate.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the threat-assessment
pass lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the broca / motor_cortex / basal_ganglia
notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/external/perception``,
``hive/sensory/auditory/text``, ``hive/sensory/auditory/features``,
``hive/sensory/visual/processed``, and ``hive/sensory/visual/features``,
notebook MUST use wildcards (``hive/sensory/+/+``,
``hive/sensory/+/+/+``, ``hive/external/+``) to cover the rest of the
sensory + external surface without colliding.

Self-receive filter: amygdala publishes ``hive/cognitive/amygdala/...``
and ``hive/modulator/cortisol`` from its respond handler; those topics
are not in our subscription set today, but the filter is defensive
symmetry with the broader handler cohort and protects against future
subscription expansion.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # 3-segment sensory wildcard. Catches ``sensory/visual/processed``,
    # ``sensory/visual/features``, ``sensory/auditory/features``,
    # ``sensory/auditory/events``, ``sensory/auditory/text``, etc. The
    # exact-topic respond.py subscriptions sit alongside via wildcard
    # overlap (allowed by the loader).
    "hive/sensory/+/+",
    # 4-segment sensory wildcard. Catches feature subtopics like
    # ``sensory/visual/features/onset``.
    "hive/sensory/+/+/+",
    # Hippocampal memory responses — exact topic. respond.py does not
    # subscribe to this, so the exact form is collision-free here.
    "hive/cognitive/hippocampus/response",
    # External envelopes (chat input, host signals). Wildcard so we pick
    # up perception, command, etc., without exact-topic collision with
    # respond.py's ``hive/external/perception``.
    "hive/external/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"sensory.visual.processed"``.

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
        # Prefer threat-relevant text fields; fall back to stringifying.
        for key in ("text", "content", "phrase", "summary", "event", "label"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # amygdala publishes threat_assessment + cortisol; none of those land
    # under our current subscriptions, but defensive symmetry with the
    # rest of the handler cohort keeps us safe against future expansion.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
