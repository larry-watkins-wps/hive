"""Observatory runtime configuration — env-var driven."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when an observatory env var is present but malformed."""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not an integer") from exc


@dataclass(frozen=True)
class Settings:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    hive_repo_root: Path = Path(".").resolve()
    max_ws_rate: int = 200  # envelopes/sec per client before decimation kicks in
    mqtt_url: str = "mqtt://127.0.0.1:1883"
    regions_root: Path = Path("regions")
    ring_buffer_size: int = 10000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            bind_host=os.environ.get("OBSERVATORY_BIND_HOST", cls.bind_host),
            bind_port=_int_env("OBSERVATORY_BIND_PORT", cls.bind_port),
            hive_repo_root=Path(
                os.environ.get("OBSERVATORY_HIVE_ROOT", str(Path(".").resolve()))
            ).resolve(),
            max_ws_rate=_int_env("OBSERVATORY_MAX_WS_RATE", cls.max_ws_rate),
            mqtt_url=os.environ.get("OBSERVATORY_MQTT_URL", cls.mqtt_url),
            regions_root=Path(
                os.environ.get("OBSERVATORY_REGIONS_ROOT", str(cls.regions_root))
            ),
            ring_buffer_size=_int_env("OBSERVATORY_RING_BUFFER_SIZE", cls.ring_buffer_size),
        )
