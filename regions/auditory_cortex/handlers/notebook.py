"""Notebook handler for auditory_cortex — STM recorder for mic / cognitive traffic.

Listens broadly across the mic hardware topic and the directed cognitive
namespace, recording a one-line summary of every envelope into
``memory.recent_events``. The sleep coordinator later inspects that
ring buffer to decide what to consolidate, and the ``respond.py`` stub
transcriber reads it as context.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the transcription pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df). Pattern mirrors
the motor_cortex / basal_ganglia / VTA / thalamus notebook templates.

Duplicate-topic constraint (handlers_loader._check_duplicate_exact_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. notebook
uses one exact (``hive/hardware/mic``) and one wildcard
(``hive/cognitive/auditory_cortex/+``); respond uses one exact
(``hive/cognitive/auditory_cortex/transcribe_request``). The wildcard-
vs-exact overlap on ``hive/cognitive/auditory_cortex/+`` vs
``transcribe_request`` is allowed by the loader.

Self-receive filter: auditory_cortex publishes
``hive/sensory/auditory/text`` from respond.py. None of notebook's
subscriptions pull that namespace today, but defensive symmetry with
respond.py and uniform pattern across handlers means the early-return
guard is here regardless. Future subscription additions on
``hive/sensory/auditory/+`` would otherwise loop self-publishes back
into STM.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Raw mic hardware input — only auditory_cortex may subscribe per
    # MQTT ACL (Principle IV: modality isolation).
    "hive/hardware/mic",
    # Directed cognitive traffic addressed to auditory_cortex (e.g.
    # transcribe_request envelopes from PFC).
    "hive/cognitive/auditory_cortex/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"hardware.mic"`` or ``"cognitive.auditory_cortex.x"``.

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
        # transcribe requests, ``description`` for hardware events,
        # ``reason`` for failures, ``summary`` for cognitive integration
        # outputs that occasionally land on cognitive/auditory_cortex/*.
        for key in ("text", "description", "summary", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # Defensive symmetry with respond.py — auditory_cortex's notebook
    # subscriptions don't currently overlap with what we publish, but a
    # future subscription change on ``hive/sensory/auditory/+`` would
    # otherwise loop self-publishes from respond back into STM.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
