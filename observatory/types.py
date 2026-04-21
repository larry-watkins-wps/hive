"""Typed records used throughout the observatory."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RingRecord:
    """One observed MQTT envelope plus derived fields."""
    observed_at: float              # monotonic seconds (time.monotonic()); origin is process-local
    topic: str
    envelope: dict[str, Any]        # parsed Envelope JSON
    source_region: str | None       # from envelope.source_region if present
    destinations: tuple[str, ...]   # inferred; empty if unknown


@dataclass
class RegionStats:
    """Rolling per-region stats, updated from heartbeats + observed traffic."""
    phase: str = "unknown"          # wake | sleep | processing | unknown
    queue_depth: int = 0
    stm_bytes: int = 0
    tokens_lifetime: int = 0
    handler_count: int = 0
    last_error_ts: str | None = None
    msg_rate_in: float = 0.0        # 5 s window, updated by adjacency
    msg_rate_out: float = 0.0
    llm_in_flight: bool = False     # inferred from recent token burn


@dataclass
class RegionMeta:
    """Static metadata about a region (from regions_registry.yaml)."""
    name: str
    role: str = ""                  # "sensory" | "cognitive" | "modulatory" | ...
    llm_model: str = ""
    stats: RegionStats = field(default_factory=RegionStats)
