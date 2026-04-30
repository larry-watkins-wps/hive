"""Notebook handler for insula — STM recorder for body signals.

Listens broadly across insula's primary inputs (system metrics,
per-region operational stats, directed cognitive requests, and ambient
modulator levels) and records a one-line summary of every envelope into
``memory.recent_events``. The sleep coordinator later inspects that ring
buffer to decide what to consolidate, and the ``respond.py`` felt-state
handler reads it as context for the LLM-driven interoception pass.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the felt-state pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the broca / motor_cortex / basal_ganglia /
amygdala notebook templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. notebook
uses only wildcard patterns; respond's subscriptions are exact topics
under ``hive/system/metrics/`` (compute / region_health / tokens) which
are wildcard-overlapped by notebook's ``hive/system/metrics/+`` — the
loader allows this. No exact-topic collision.

Self-receive filter: insula publishes ``hive/interoception/felt_state``
(retained) and may publish ``hive/cognitive/insula/*`` responses. The
``hive/modulator/+`` and ``hive/cognitive/insula/+`` subscriptions would
otherwise feed our own publishes back into STM. Early-return when
``envelope.source_region == ctx.region_name``.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # System metrics (compute, tokens, region_health, queue_depth, etc.).
    # Wildcard-overlaps respond.py's exact subscriptions; loader allows this.
    "hive/system/metrics/+",
    # Per-region operational statistics (msg/s, latency, error rate, etc.).
    "hive/system/region_stats/+",
    # Directed cognitive requests that name us specifically.
    "hive/cognitive/insula/+",
    # Ambient modulator levels — context for felt_state interpretation.
    # (e.g., elevated cortisol biases toward "stressed" felt states.)
    "hive/modulator/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"system.metrics.compute"`` or ``"modulator.dopamine"``.

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
        # Prefer fields that carry a meaningful one-liner. ``rationale``
        # for modulator envelopes, ``summary`` for region_stats rollups,
        # ``state`` for felt-state-shaped payloads, ``text``/``label`` for
        # directed cognitive requests.
        for key in ("rationale", "summary", "state", "text", "label", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # insula publishes ``hive/interoception/felt_state`` and may publish
    # cognitive/insula/* responses; without this filter those would feed
    # back into STM via the ``hive/cognitive/insula/+`` and
    # ``hive/modulator/+`` wildcards (defensive symmetry).
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
