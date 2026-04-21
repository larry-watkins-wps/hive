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


@pytest.mark.asyncio
async def test_two_appends_produce_two_sections_in_order(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    region_root.mkdir(parents=True)
    store = AppendixStore(region_root)

    await store.append(
        "first cycle insight",
        when=datetime(2026, 4, 22, 3, 14, 0, tzinfo=UTC),
        trigger="quiet_window",
    )
    await store.append(
        "second cycle insight",
        when=datetime(2026, 4, 22, 9, 41, 0, tzinfo=UTC),
        trigger="quiet_window",
    )

    body = store.path.read_text(encoding="utf-8")
    first_idx = body.index("first cycle insight")
    second_idx = body.index("second cycle insight")
    assert first_idx < second_idx
    assert body.count("## 2026-04-22T03:14:00+00:00") == 1
    assert body.count("## 2026-04-22T09:41:00+00:00") == 1


@pytest.mark.asyncio
async def test_external_content_is_preserved(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    (region_root / "memory" / "appendices").mkdir(parents=True)
    rolling = region_root / "memory" / "appendices" / "rolling.md"
    rolling.write_text(
        "# Rolling appendix\n\nSome notes I pasted in by hand.\n",
        encoding="utf-8",
    )

    store = AppendixStore(region_root)
    await store.append(
        "scheduled insight",
        when=datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC),
        trigger="sleep",
    )

    body = rolling.read_text(encoding="utf-8")
    assert "Some notes I pasted in by hand." in body
    assert "scheduled insight" in body
    assert body.index("Some notes I pasted in by hand.") < body.index("scheduled insight")
