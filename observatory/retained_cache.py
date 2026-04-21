"""Retained-topic cache — one latest envelope per topic."""
from __future__ import annotations

from typing import Any


class RetainedCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def put(self, topic: str, envelope: dict[str, Any]) -> None:
        self._data[topic] = envelope

    def get(self, topic: str) -> dict[str, Any] | None:
        return self._data.get(topic)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)

    def keys_matching(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]
