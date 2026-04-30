"""Notebook handler for thalamus — STM recorder for sensory + cognitive traffic.

Listens broadly across the sensory namespace and cognitive integration
outputs that thalamus might need to route, recording a one-line summary
of every envelope into ``memory.recent_events``. The sleep coordinator
later inspects that ring buffer to decide what to consolidate, and the
``respond.py`` routing handler reads it as gating context.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the routing decision
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df). Pattern mirrors
the motor_cortex / basal_ganglia / VTA notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. notebook
uses only wildcard patterns; respond's subscriptions are exact
(``hive/cognitive/thalamus/route_request``) and a wildcard
(``hive/cognitive/+/integration``). The notebook wildcard
``hive/cognitive/thalamus/+`` overlaps with respond's exact
``route_request`` — that is the wildcard-vs-exact case which the loader
allows. respond's ``hive/cognitive/+/integration`` and notebook's
``hive/cognitive/+/integration`` are both wildcards so wildcard-vs-
wildcard overlap is also allowed (the loader only blocks exact-vs-exact
across files).

Self-receive filter: thalamus publishes ``hive/cognitive/thalamus/route``
from respond.py. The wildcard ``hive/cognitive/thalamus/+`` would
otherwise feed those self-publishes back into STM. The handler
early-returns when ``envelope.source_region == ctx.region_name``.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Sensory streams, 3-segment. Catches ``auditory/text``,
    # ``visual/scene``, etc.
    "hive/sensory/+/+",
    # Sensory streams, 4-segment. Catches deeper-namespaced subtopics
    # without forcing a respond.py override.
    "hive/sensory/+/+/+",
    # Directed cognitive traffic addressed to thalamus.
    "hive/cognitive/thalamus/+",
    # Integration outputs from any cortex — thalamus watches these for
    # ambiguous cross-region traffic that may need routing hints.
    "hive/cognitive/+/integration",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"sensory.auditory.text"`` or ``"cognitive.thalamus.x"``.

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
        # Prefer fields that carry a meaningful one-liner across the
        # subscribed topics: ``text`` (auditory transcripts), ``summary``
        # (integration outputs), ``description`` (event descriptions),
        # ``rationale`` (routing/integration rationale), ``reason``
        # (failures / requests).
        for key in ("text", "summary", "description", "rationale", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # thalamus publishes ``hive/cognitive/thalamus/route`` from
    # respond.py which the wildcard ``hive/cognitive/thalamus/+`` would
    # otherwise feed back into STM.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
