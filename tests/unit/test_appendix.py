"""Unit tests for :mod:`region_template.appendix`.

The appendix store is the single writer of
``regions/<name>/memory/appendices/rolling.md``. It must:
  - lazy-create the file + parent dir on first append,
  - prepend an ISO-timestamped H2 header to every entry,
  - append atomically (read-modify-write via ``_atomic_write_text``),
  - tolerate externally-authored edits (runtime only guarantees
    "sleep appends"; it does not own the file exclusively).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from region_template.appendix import AppendixStore


@pytest.mark.asyncio
async def test_append_lazy_creates_file_and_parent(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    region_root.mkdir(parents=True)
    store = AppendixStore(region_root)

    rolling = region_root / "memory" / "appendices" / "rolling.md"
    assert not rolling.exists()
    assert not rolling.parent.exists()

    await store.append(
        "Observed that text input produced no speech intent.",
        when=datetime(2026, 4, 22, 3, 14, 0, tzinfo=UTC),
        trigger="quiet_window",
    )

    assert rolling.is_file()
    body = rolling.read_text(encoding="utf-8")
    assert "## 2026-04-22T03:14:00+00:00 — quiet_window" in body
    assert "Observed that text input produced no speech intent." in body
