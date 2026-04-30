"""Notebook handler for visual_cortex — STM recorder for camera / cognitive traffic.

Listens broadly across the camera hardware topic and the directed
cognitive namespace, recording a one-line summary of every envelope
into ``memory.recent_events``. The sleep coordinator later inspects
that ring buffer to decide what to consolidate, and the ``respond.py``
stub captioner reads it as context.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the captioning pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df). Pattern mirrors
the auditory_cortex notebook (its symmetric sibling) and the broader
notebook templates across the cohort.

Duplicate-topic constraint (handlers_loader._check_duplicate_exact_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. notebook
uses one exact (``hive/hardware/camera``) and one wildcard
(``hive/cognitive/visual_cortex/+``); respond uses one exact
(``hive/cognitive/visual_cortex/caption_request``). The wildcard-
vs-exact overlap on ``hive/cognitive/visual_cortex/+`` vs
``caption_request`` is allowed by the loader.

Self-receive filter: visual_cortex publishes
``hive/sensory/visual/text`` from respond.py. None of notebook's
subscriptions pull that namespace today, but defensive symmetry with
respond.py and uniform pattern across handlers means the early-return
guard is here regardless. Future subscription additions on
``hive/sensory/visual/+`` would otherwise loop self-publishes back
into STM.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Raw camera hardware input — only visual_cortex may subscribe per
    # MQTT ACL (Principle IV: modality isolation).
    "hive/hardware/camera",
    # Directed cognitive traffic addressed to visual_cortex (e.g.
    # caption_request envelopes from PFC).
    "hive/cognitive/visual_cortex/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"hardware.camera"`` or ``"cognitive.visual_cortex.x"``.

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
        # Prefer fields that carry a meaningful one-liner: ``text`` for
        # caption requests, ``description`` for hardware events,
        # ``reason`` for failures, ``summary`` for cognitive integration
        # outputs that occasionally land on cognitive/visual_cortex/*.
        for key in ("text", "description", "summary", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # Defensive symmetry with respond.py — visual_cortex's notebook
    # subscriptions don't currently overlap with what we publish, but a
    # future subscription change on ``hive/sensory/visual/+`` would
    # otherwise loop self-publishes from respond back into STM.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
