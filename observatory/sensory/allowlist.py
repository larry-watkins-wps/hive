"""Topic allowlist — the boundary that keeps observatory's write surface narrow.

v4: only `hive/external/perception` (translator output for chat-typed input).
Future PRs add topics by editing this set + updating the v4 spec §4.2.
"""
from __future__ import annotations

ALLOWED_PUBLISH_TOPICS: frozenset[str] = frozenset({
    "hive/external/perception",
})
