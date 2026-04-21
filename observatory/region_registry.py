"""Region registry: names/roles seeded from YAML, stats from heartbeats."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from observatory.types import RegionMeta

_YAML = YAML(typ="safe")


def _coerce_int(value: Any, fallback: int) -> int:
    """Best-effort int coercion that falls back on None / non-numeric input.

    Heartbeats arrive from the wild; a region may stub a metric as `null` or
    emit a string, and the observatory must degrade rather than drop the
    whole update.
    """
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class RegionRegistry:
    def __init__(self) -> None:
        self._regions: dict[str, RegionMeta] = {}

    @classmethod
    def seed_from(cls, hive_repo_root: Path) -> RegionRegistry:
        """Load region names + metadata from ``glia/regions_registry.yaml``.

        The canonical schema is a top-level mapping keyed by region name, e.g.::

            regions:
              thalamus:
                layer: cognitive
                required_capabilities: [tool_use]

        ``layer`` populates ``RegionMeta.role`` (same concept, different name
        upstream). Missing file, empty file, malformed top-level, or malformed
        entries all result in an empty / partial registry rather than an
        exception — the observatory is a read-only sidecar and must not crash
        on Hive-side schema drift.
        """
        reg = cls()
        yaml_path = hive_repo_root / "glia" / "regions_registry.yaml"
        if not yaml_path.exists():
            return reg
        data = _YAML.load(yaml_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return reg
        regions = data.get("regions")
        if not isinstance(regions, dict):
            return reg
        for name, entry in regions.items():
            if not name or not isinstance(entry, dict):
                continue
            reg._regions[str(name)] = RegionMeta(
                name=str(name),
                role=str(entry.get("layer", "")),
                llm_model=str(entry.get("llm_model", "")),
            )
        return reg

    def names(self) -> list[str]:
        return list(self._regions.keys())

    def get(self, name: str) -> RegionMeta:
        return self._regions[name]

    def apply_heartbeat(self, name: str, payload: dict[str, Any]) -> None:
        meta = self._regions.get(name)
        if meta is None:
            meta = RegionMeta(name=name)
            self._regions[name] = meta
        s = meta.stats
        s.phase = str(payload.get("phase", s.phase))
        s.queue_depth = _coerce_int(payload.get("queue_depth_messages"), s.queue_depth)
        s.stm_bytes = _coerce_int(payload.get("stm_bytes"), s.stm_bytes)
        s.tokens_lifetime = _coerce_int(
            payload.get("llm_tokens_used_lifetime"), s.tokens_lifetime
        )
        s.handler_count = _coerce_int(payload.get("handler_count"), s.handler_count)
        s.last_error_ts = payload.get("last_error_ts", s.last_error_ts)

    def to_json(self) -> dict[str, Any]:
        return {
            name: {
                "role": m.role,
                "llm_model": m.llm_model,
                "stats": {
                    "phase": m.stats.phase,
                    "queue_depth": m.stats.queue_depth,
                    "stm_bytes": m.stats.stm_bytes,
                    "tokens_lifetime": m.stats.tokens_lifetime,
                    "handler_count": m.stats.handler_count,
                    "last_error_ts": m.stats.last_error_ts,
                    "msg_rate_in": m.stats.msg_rate_in,
                    "msg_rate_out": m.stats.msg_rate_out,
                    "llm_in_flight": m.stats.llm_in_flight,
                },
            }
            for name, m in self._regions.items()
        }
