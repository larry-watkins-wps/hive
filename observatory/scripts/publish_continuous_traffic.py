# ruff: noqa: E501, PLR2004 — dev diagnostic script: long tabular factory
# definitions and literal timing/weight constants are clearer inline than
# extracted into named symbols.
"""Publish continuous, randomized cross-region traffic to the Hive broker.

Where `publish_demo_traffic.py` plays a fixed 14-envelope script in order over
~30 s, this script emits steady, varied traffic for a configurable duration
so the observatory has something alive to render beyond heartbeats/rhythms.

Usage (from repo root, with the observatory stack running):

    .venv/Scripts/python.exe observatory/scripts/publish_continuous_traffic.py [--duration 120] [--rate 12]

--duration : seconds to run (default 120).
--rate     : approximate messages per second (default 12). Inter-message
             delay is drawn uniform in [0.5/rate, 1.5/rate] so bursts and
             lulls look organic.

The message pool below models realistic biological wiring: modulator updates
from their canonical publishers, sensory bursts from visual/auditory cortex,
planning chains through mPFC → ACC → basal_ganglia → motor_cortex, and
hippocampal memory queries. Every topic has at least one subscribing region
(per `regions/*/subscriptions.yaml`) so every publish produces at least one
spark.

Like the fixed script, this is a developer diagnostic — MQTT publishes only,
no region filesystem writes, no cosign-gated channels touched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from typing import Any

import aiomqtt

# Windows default event loop is Proactor, which does not implement
# add_reader/add_writer — aiomqtt (via paho) needs both. Swap to
# Selector before asyncio.run installs a loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883


def _rnd(lo: float, hi: float) -> float:
    return lo + (hi - lo) * random.random()


# Factories return (source_region, topic, payload) tuples. Each call produces
# fresh values so repeated emissions look like ongoing state drift, not a
# replay loop.
def mod_cortisol():      return ("amygdala",                 "hive/modulator/cortisol",          {"value": round(_rnd(0.1, 0.7), 2)})
def mod_dopamine():      return ("vta",                      "hive/modulator/dopamine",          {"value": round(_rnd(0.2, 0.9), 2)})
def mod_serotonin():     return ("basal_ganglia",            "hive/modulator/serotonin",         {"value": round(_rnd(0.3, 0.8), 2)})
def mod_norepinephrine():return ("motor_cortex",             "hive/modulator/norepinephrine",    {"value": round(_rnd(0.2, 0.7), 2)})
def mod_oxytocin():      return ("insula",                   "hive/modulator/oxytocin",          {"value": round(_rnd(0.0, 0.6), 2)})
def mod_acetylcholine(): return ("anterior_cingulate",       "hive/modulator/acetylcholine",     {"value": round(_rnd(0.2, 0.9), 2)})

def sensory_visual():    return ("visual_cortex",            "hive/sensory/visual/processed",    {"frame_id": random.randint(1, 9999), "features": random.sample(["motion", "face", "edge", "text", "color"], k=random.randint(1, 3))})
def sensory_auditory():  return ("auditory_cortex",          "hive/sensory/auditory/text",       {"transcript": random.choice(["hello", "what's next", "silence", "tone shift", "ambient noise"])})

def attn_focus():        return ("anterior_cingulate",       "hive/attention/focus",             {"target": random.choice(["prefrontal_cortex", "visual_cortex", "auditory_cortex", "hippocampus", "insula"])})
def attn_gating():       return ("thalamus",                 "hive/attention/gating",            {"allow": random.sample(["sensory/visual", "sensory/auditory", "interoception", "metacognition"], k=random.randint(1, 3))})

def intero_felt():       return ("insula",                   "hive/interoception/felt_state",    {"value": random.choice(["calm", "alert", "restless", "engaged", "tired"])})

def self_identity():     return ("medial_prefrontal_cortex", "hive/self/identity",               {"value": "I am Hive — a distributed cognitive system."})
def self_values():       return ("association_cortex",       "hive/self/values",                 {"values": random.sample(["curiosity", "integrity", "care", "truth", "play"], k=random.randint(2, 4))})
def self_felt():         return ("broca_area",               "hive/self/felt_state",             {"value": random.choice(["ready", "thinking", "listening", "composing"])})

def cog_plan():          return ("prefrontal_cortex",        "hive/cognitive/prefrontal/plan",   {"plan": random.choice([["observe", "decide"], ["observe", "orient", "decide", "act"], ["recall", "compare", "answer"]])})
def cog_hippo_query():   return ("hippocampus",              "hive/cognitive/hippocampus/query", {"key": random.choice(["last_sleep_cycle", "recent_faces", "today_events", "goal_stack"])})
def cog_assoc():         return ("association_cortex",       "hive/cognitive/association_cortex/bind",
                                                                                                   {"bind": random.choice(["visual+auditory", "memory+affect", "self+goal"])})

def motor_speech():      return ("broca_area",               "hive/motor/speech/intent",         {"text": random.choice(["noted", "one moment", "continuing", "acknowledged"])})

# Weight the pool so biologically-frequent signals (modulators, rhythms,
# attention shifts) fire more often than rare events (identity changes).
POOL: list[tuple[int, Any]] = [
    # (weight, factory)
    (6, mod_cortisol),
    (6, mod_dopamine),
    (4, mod_serotonin),
    (4, mod_norepinephrine),
    (2, mod_oxytocin),
    (3, mod_acetylcholine),

    (5, sensory_visual),
    (5, sensory_auditory),

    (6, attn_focus),
    (5, attn_gating),

    (4, intero_felt),

    (1, self_identity),  # rare — identity shifts are slow
    (2, self_values),
    (3, self_felt),

    (5, cog_plan),
    (4, cog_hippo_query),
    (3, cog_assoc),

    (3, motor_speech),
]
_WEIGHTED_POOL: list[Any] = []
for w, fn in POOL:
    _WEIGHTED_POOL.extend([fn] * w)


def build_envelope(topic: str, source: str, payload: dict[str, Any]) -> bytes:
    """Envelope matching `schemas/envelope/v1.json` — same shape as the fixed
    demo script. Region handlers validate strictly so every field matters."""
    ts = time.gmtime()
    millis = int((time.time() % 1) * 1000)
    envelope = {
        "id": str(uuid.uuid4()),
        "timestamp": f"{time.strftime('%Y-%m-%dT%H:%M:%S', ts)}.{millis:03d}Z",
        "source_region": source,
        "topic": topic,
        "payload": payload,
        "envelope_version": 1,
    }
    return json.dumps(envelope).encode("utf-8")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--rate", type=float, default=12.0, help="approx msgs/sec")
    args = ap.parse_args()

    # Uniquify the client id in case multiple copies run back-to-back.
    client_id = f"hive-continuous-{__import__('os').getpid()}-{int(time.time())}"
    mean_delay = 1.0 / max(args.rate, 0.1)

    async with aiomqtt.Client(
        hostname=BROKER_HOST, port=BROKER_PORT, identifier=client_id
    ) as client:
        print(f"Connected to mqtt://{BROKER_HOST}:{BROKER_PORT}")
        print(f"Streaming ~{args.rate:.0f} msg/s for {args.duration:.0f}s…")

        end = time.monotonic() + args.duration
        count = 0
        t_last_report = time.monotonic()
        while time.monotonic() < end:
            factory = random.choice(_WEIGHTED_POOL)
            source, topic, payload = factory()
            body = build_envelope(topic, source, payload)
            await client.publish(topic, payload=body, qos=1)
            count += 1
            # Per-message jitter in [0.5, 1.5]× mean_delay so rate looks
            # organic — real Hive traffic arrives in bursts and lulls.
            await asyncio.sleep(_rnd(0.5 * mean_delay, 1.5 * mean_delay))
            now = time.monotonic()
            if now - t_last_report >= 10.0:
                remaining = max(0, int(end - now))
                print(f"  …{count} sent, ~{remaining}s remaining")
                t_last_report = now

        print(f"\nDone. Sent {count} envelopes in ~{args.duration:.0f}s.")


if __name__ == "__main__":
    asyncio.run(main())
