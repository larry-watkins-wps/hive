"""Publish a short burst of demo traffic to exercise the observatory's
edge/spark pipeline end-to-end without waiting for organic Hive activity.

The observatory infers destinations from `regions/<name>/subscriptions.yaml`
subscriptions. Publishing on subscribed topics with a `source_region` field
set causes the observatory to record (source -> destination) pairs in its
rolling adjacency matrix, which the frontend renders as threads + sparks.

Usage (from repo root, with the observatory stack running):

    .venv/Scripts/python.exe observatory/scripts/publish_demo_traffic.py

This is a developer diagnostic, not part of Hive's runtime. It does not
write to any region filesystem — publishes are MQTT only, and none target
the cosign-gated code-change path.
"""
from __future__ import annotations

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
# Selector before asyncio.run installs a loop. Same gotcha as
# observatory/service.py and tests/component/conftest.py.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883

# A small script of representative cross-region chatter. Each entry is
# (source_region, topic, payload). Topics are chosen so that at least one
# OTHER region subscribes to them (per regions/*/subscriptions.yaml):
#
# - hive/self/#             : every region subscribes (base bundle)
# - hive/modulator/#        : every region subscribes (base bundle)
# - hive/attention/#        : every region subscribes (base bundle)
# - hive/interoception/#    : every region subscribes (base bundle)
# - hive/sensory/visual/#   : thalamus + amygdala + visual_cortex + …
# - hive/cognitive/prefrontal/plan : thalamus + ACC + others
SCRIPT: list[tuple[str, str, dict[str, Any]]] = [
    ("medial_prefrontal_cortex", "hive/self/identity",
     {"value": "I am Hive — a distributed cognitive system."}),
    ("vta", "hive/modulator/dopamine", {"value": 0.62}),
    ("amygdala", "hive/modulator/cortisol", {"value": 0.31}),
    ("visual_cortex", "hive/sensory/visual/processed",
     {"frame_id": 42, "features": ["motion", "face"]}),
    ("auditory_cortex", "hive/sensory/auditory/text",
     {"transcript": "hello"}),
    ("prefrontal_cortex", "hive/cognitive/prefrontal/plan",
     {"plan": ["observe", "orient", "decide", "act"]}),
    ("anterior_cingulate", "hive/attention/focus",
     {"target": "prefrontal_cortex"}),
    ("insula", "hive/interoception/felt_state",
     {"value": "calm"}),
    ("hippocampus", "hive/cognitive/hippocampus/query",
     {"key": "last_sleep_cycle"}),
    ("basal_ganglia", "hive/modulator/serotonin", {"value": 0.47}),
    ("thalamus", "hive/attention/gating",
     {"allow": ["sensory/visual", "sensory/auditory"]}),
    ("motor_cortex", "hive/modulator/norepinephrine", {"value": 0.55}),
    ("broca_area", "hive/self/felt_state",
     {"value": "ready"}),
    ("association_cortex", "hive/self/values",
     {"values": ["curiosity", "integrity"]}),
]


def build_envelope(topic: str, source: str, payload: dict[str, Any]) -> bytes:
    """Build an envelope matching Hive's v1 schema exactly so consumers that
    validate strictly (like region handlers) accept it.

    Required fields per `schemas/envelope/v1.json`:
      id               UUIDv4 string
      timestamp        RFC 3339 millisecond UTC
      source_region    ^[a-z][a-z0-9_]{2,30}$
      topic            non-empty string
      payload          any JSON value
      envelope_version 1
    `additionalProperties: false`, so nothing else is tolerated.
    """
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
    # Client identifier is required by some brokers (e.g. RxMqtt.Broker);
    # aiomqtt defaults to an empty string which those brokers reject. The
    # value is per-connection so uniquify it with a pid + timestamp suffix
    # in case two copies of this script run back-to-back.
    client_id = f"hive-demo-publisher-{__import__('os').getpid()}-{int(time.time())}"
    async with aiomqtt.Client(hostname=BROKER_HOST, port=BROKER_PORT, identifier=client_id) as client:
        print(f"Connected to mqtt://{BROKER_HOST}:{BROKER_PORT}")
        print(f"Publishing {len(SCRIPT)} demo envelopes over ~30s…")
        for i, (source, topic, payload) in enumerate(SCRIPT, start=1):
            body = build_envelope(topic, source, payload)
            await client.publish(topic, payload=body, qos=1)
            print(f"  [{i:>2}/{len(SCRIPT)}] {source:>24s}  ->  {topic}")
            # Space out publishes so sparks have time to visibly travel
            # before the next burst. 2 s is comfortable at default spark
            # lifetime of 800 ms plus adjacency windowing.
            await asyncio.sleep(2.0 + random.random() * 0.5)
        print("\nDone. Re-run to replay — observatory's adjacency window is 5 s,")
        print("so edges will fade out ~5 s after the last publish on each pair.")


if __name__ == "__main__":
    asyncio.run(main())
