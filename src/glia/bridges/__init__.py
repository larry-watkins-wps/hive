"""Glia hardware and rhythm bridges — spec §E.7 / §E.8.

Each bridge translates an external input/output (hardware device or
TCP socket) to/from MQTT topics. Bridges are deliberately "dumb" — no
cognition; just I/O pumps owned by the glia supervisor.

At v0, only ``input_text_bridge`` is enabled by default. Audio, camera,
and motor bridges require explicit operator opt-in (``enabled=True``).
When a bridge cannot initialize (missing dep, no device), it publishes
``hive/system/metrics/hardware/<name> = {"status": "unavailable", ...}``
instead of crashing glia.
"""
from __future__ import annotations

from glia.bridges.camera_bridge import CameraBridge
from glia.bridges.input_text_bridge import InputTextBridge
from glia.bridges.mic_bridge import MicBridge
from glia.bridges.motor_bridge import MotorBridge
from glia.bridges.rhythm_generator import RhythmGenerator
from glia.bridges.speaker_bridge import SpeakerBridge

__all__ = [
    "CameraBridge",
    "InputTextBridge",
    "MicBridge",
    "MotorBridge",
    "RhythmGenerator",
    "SpeakerBridge",
]
