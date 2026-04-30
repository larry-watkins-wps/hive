"""Notebook handler for anterior_cingulate — STM recorder for metacog context.

Listens broadly across the streams ACC monitors for conflict / error /
spawn / codechange awareness, and records a one-line summary of every
envelope into ``memory.recent_events``. The sleep coordinator later
inspects that ring buffer to decide what to consolidate, and the
``respond.py`` conflict-detection handler reads it as the prior-context
window against which the current envelope is compared for divergence.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the conflict-detection
pass lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the motor_cortex / basal_ganglia / VTA
notebook templates.

Duplicate-topic constraint (handlers_loader._check_duplicate_exact_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed
(wildcard-vs-wildcard and wildcard-vs-exact are fanout, not conflict).
notebook uses wildcards (``hive/metacognition/+`` 3-segment +
``hive/metacognition/+/+`` 4-segment + ``hive/cognitive/+/+``);
respond uses the wildcard ``hive/cognitive/+/integration`` plus the
exact ``hive/cognitive/prefrontal_cortex/plan`` — the wildcard-vs-wildcard
overlap on ``hive/cognitive/+/+`` is allowed by the loader. The exact
``hive/system/{spawn,codechange}/proposed`` subscriptions are unique to
notebook and don't collide with respond.

Self-receive filter: defensive symmetry with respond.py. ACC publishes
``hive/metacognition/conflict/detected`` (and historically
``hive/metacognition/conflict/observed`` /
``hive/metacognition/reflection/response``) which match the
``hive/metacognition/+`` and ``hive/metacognition/+/+`` wildcards.
Without the filter those self-publishes would feed back into STM —
biologically odd and inflates the conflict-detection context.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Metacognition surface, 3-segment. Catches future 3-segment
    # metacog subtopics (e.g. ``hive/metacognition/health``).
    "hive/metacognition/+",
    # Metacognition surface, 4-segment. Catches the canonical
    # ``error/detected``, ``conflict/detected`` (our own output —
    # filtered by self-receive), ``reflection/request``,
    # ``reflection/response``, etc.
    "hive/metacognition/+/+",
    # System proposals requiring ACC deliberation. Exact topics; unique
    # to notebook (respond does not subscribe to system/*).
    "hive/system/spawn/proposed",
    "hive/system/codechange/proposed",
    # Cognitive streams — broader than respond's ``+/integration`` so
    # ACC also sees plan / threat_assessment / reflection / etc. for
    # divergence context. Wildcard-vs-wildcard overlap with respond's
    # ``hive/cognitive/+/integration`` is allowed by the loader.
    "hive/cognitive/+/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"metacognition.error.detected"``.

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
        # heterogeneous payload shapes ACC observes:
        # - ``summary`` for cognitive integration / plan outputs
        # - ``rationale`` for metacog responses and codechange proposals
        # - ``kind`` for metacog/error/detected payloads
        # - ``name`` / ``role`` for spawn/proposed payloads
        # - ``text`` as a last-resort generic field
        for key in ("summary", "rationale", "kind", "name", "role", "text"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # ACC publishes ``hive/metacognition/conflict/detected`` (and other
    # metacog outputs); without the filter those would feed back into
    # STM via the ``hive/metacognition/+/+`` wildcard.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
