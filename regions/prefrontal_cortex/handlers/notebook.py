"""Starter handler — record inbound sensory text into STM so that sleep
has something to consolidate.

Scope is deliberately tiny: subscribe to sensory text, take the first line of
payload text as the summary, and append. The next sleep cycle will see the
recent_events buffer and can reason about whether a richer handler or
subscription set is warranted.

This is the one concession to "regions arrive with nothing" — v0 scaffolds
ship empty handlers, which means STM never accumulates, which means the first
sleep cycle always returns ``no_change``. The region may replace or evolve
this handler during its first self-mod cycle.
"""
from __future__ import annotations

SUBSCRIPTIONS = ["hive/sensory/input/text"]
TIMEOUT_S = 5.0


async def handle(envelope, ctx):
    data = envelope.payload.data
    if isinstance(data, dict):
        text = data.get("text", "")
    else:
        text = str(data)[:200]
    if not isinstance(text, str):
        text = str(text)
    summary = f"sensory.text: {text[:200]}"
    await ctx.memory.record_event(envelope, summary)
