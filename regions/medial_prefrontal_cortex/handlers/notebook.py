"""Notebook handler for mPFC — STM recorder for reflection traffic.

Listens to reflection requests + responses (the request side is what
``respond.py`` reasons over; the response side is what other regions
publish back, which mPFC also wants in STM for self-state continuity)
plus its own directed-cognitive channel, and records a one-line summary
of every envelope into ``memory.recent_events``. The sleep coordinator
later inspects that ring buffer to decide what to consolidate, and
``respond.py``'s LLM call reads it for context when reasoning about the
next reflection.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the reflection-response
pass lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors VTA's notebook template (post-f99b812).

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/metacognition/reflection/
request`` topic, notebook MUST use a wildcard
(``hive/metacognition/reflection/+``) so the loader's exact-vs-exact
collision check passes. Wildcard-vs-exact overlap is fine.

Self-receive filter: defensive symmetry with respond.py. mPFC publishes
``hive/metacognition/reflection/response`` itself, so the
``reflection/+`` wildcard would otherwise feed our own outputs back into
STM and inflate the ring buffer with our own voice.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Reflection request + response. Wildcard avoids exact-topic
    # collision with respond.py's ``hive/metacognition/reflection/
    # request`` subscription. Catches ``request`` and ``response`` (and
    # any future reflection subtopic).
    "hive/metacognition/reflection/+",
    # Directed-cognitive channel: messages addressed at mPFC.
    "hive/cognitive/medial_prefrontal_cortex/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"metacognition.reflection.request"``.

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
        # Prefer ``topic_to_reflect_on`` (reflection/request), then
        # ``reflection`` (reflection/response), then ``observation``,
        # then ``trigger``, then stringify the whole dict.
        for key in ("topic_to_reflect_on", "reflection", "observation", "trigger"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # mPFC publishes ``hive/metacognition/reflection/response`` itself,
    # so the ``reflection/+`` wildcard would otherwise feed our own
    # outputs back into STM.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
