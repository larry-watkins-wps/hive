"""Notebook handler for VTA — STM recorder for motor outcomes.

Listens broadly across motor outcome topics — the inputs from which VTA
computes a dopamine reward signal — and records a one-line summary of
every envelope into ``memory.recent_events``. The sleep coordinator
later inspects that ring buffer to decide what to consolidate, and
``respond.py``'s LLM call reads it for context when reasoning about the
next dopamine value.

This handler does not call the LLM and does not publish. It is the cheap
"this happened during wake" pen-and-paper pass; the reward-signal pass
lives in ``respond.py``.

Authority: bootstrap mode (CLAUDE.md commit 42e60df) — this subscription
set ships in the same commit as the new respond.py and the prompt
revision. Pattern mirrors the motor_cortex / basal_ganglia notebook
templates.

Duplicate-topic constraint (handlers_loader._check_no_duplicate_topics):
exact-topic collisions across handler files in the same region hard-fail
the container at boot, but overlapping wildcards are allowed. Because
``respond.py`` subscribes to the exact ``hive/motor/{complete,failed,
speech/complete}`` topics, notebook MUST use wildcards
(``hive/motor/+`` 3-segment + ``hive/motor/+/+`` 4-segment) so the
loader's exact-vs-exact collision check passes. Wildcard-vs-exact
overlap is fine.

Self-receive filter: defensive symmetry with respond.py. VTA does not
currently publish ``hive/motor/*`` topics itself, but a misrouted
self-publish or a future subscription change should not feed back into
its own STM via the wildcard subscriptions.
"""
from __future__ import annotations

SUBSCRIPTIONS = [
    # Motor topics, 3-segment. Wildcard avoids exact-topic collision with
    # respond.py's ``hive/motor/{complete,failed}`` subscriptions. Catches
    # ``complete``, ``failed``, and any future 3-segment motor subtopic.
    "hive/motor/+",
    # Motor topics, 4-segment. Catches ``speech/complete`` (broca's
    # speech outcome) and any future 4-segment motor subtopic.
    "hive/motor/+/+",
]
TIMEOUT_S = 5.0


def _shorthand(topic: str) -> str:
    """Build a short topic prefix like ``"motor.complete"`` or ``"motor.speech.complete"``.

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
        # Prefer ``description`` (motor/complete), then ``reason``
        # (motor/failed), then ``text`` (motor/speech/complete), then
        # ``action``, then stringify the whole dict.
        for key in ("description", "reason", "text", "action"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        return str(data)
    return str(data)


async def handle(envelope, ctx):
    # Self-receive filter: skip envelopes originating from this region.
    # Defensive symmetry with respond.py — VTA does not currently
    # publish motor/* topics, but the wildcard subscriptions would catch
    # any future self-publish.
    if envelope.source_region == ctx.region_name:
        return

    text = _extract_text(envelope.payload.data)
    summary = f"{_shorthand(envelope.topic)}: {text[:200]}"
    await ctx.memory.record_event(envelope, summary=summary)
