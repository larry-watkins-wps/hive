"""Observatory runtime configuration — env-var driven."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    mqtt_url: str = "mqtt://127.0.0.1:1883"
    ring_buffer_size: int = 10000
    max_ws_rate: int = 200  # envelopes/sec per client before decimation kicks in
    hive_repo_root: Path = Path(".").resolve()

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            bind_host=os.environ.get("OBSERVATORY_BIND_HOST", cls.bind_host),
            bind_port=int(os.environ.get("OBSERVATORY_BIND_PORT", cls.bind_port)),
            mqtt_url=os.environ.get("OBSERVATORY_MQTT_URL", cls.mqtt_url),
            ring_buffer_size=int(
                os.environ.get("OBSERVATORY_RING_BUFFER_SIZE", cls.ring_buffer_size)
            ),
            max_ws_rate=int(os.environ.get("OBSERVATORY_MAX_WS_RATE", cls.max_ws_rate)),
            hive_repo_root=Path(
                os.environ.get("OBSERVATORY_HIVE_ROOT", str(Path(".").resolve()))
            ).resolve(),
        )
