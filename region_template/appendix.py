"""Append-only prompt-evolution store.

Writes ``regions/<name>/memory/appendices/rolling.md`` — the single
per-region rolling appendix that the runtime concatenates onto the
system prompt at every LLM call (see :mod:`region_template.prompt_assembly`).

Design choices (see
``docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md``):

- Lazy-create: the file and its parent dir are created on the first
  successful append. No spawn-time scaffolding.
- Dated H2 headers: every entry is framed with
  ``## <ISO-timestamp> — <trigger>`` so the file is human-scannable
  and chronological.
- Atomic read-modify-write: Windows raw-append mode can partial-write
  under contention, and we already ship an atomic helper in
  :mod:`region_template.self_modify`. Reuse it.
- Tolerate external edits: the runtime's only contract is
  "sleep appends"; anything the user pastes in between cycles is
  preserved verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from region_template.self_modify import _atomic_write_text

_APPENDIX_SUBPATH = Path("memory") / "appendices" / "rolling.md"


class AppendixStore:
    """Single writer for ``rolling.md``. One instance per region."""

    def __init__(self, region_root: Path) -> None:
        self._region_root = region_root

    @property
    def path(self) -> Path:
        """Absolute path to the rolling appendix (may not yet exist)."""
        return self._region_root / _APPENDIX_SUBPATH

    async def append(
        self,
        entry: str,
        *,
        when: datetime | None = None,
        trigger: str = "sleep",
    ) -> None:
        """Append ``entry`` under a dated H2 header.

        Args:
            entry: The appendix body — a single paragraph of insight
                the region wants to commit to its evolving self.
                Whitespace-trimmed before writing.
            when: Timestamp for the header. Defaults to ``now(UTC)``.
            trigger: Short label for the header (e.g.
                ``"quiet_window"``, ``"cortisol_spike"``, ``"sleep"``).
        """
        stamp = (when or datetime.now(UTC)).isoformat(timespec="seconds")
        header = f"## {stamp} — {trigger}"
        body = entry.strip()
        section = f"{header}\n\n{body}\n"

        target = self.path
        existing = ""
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing and not existing.endswith("\n"):
                existing += "\n"
            if existing:
                existing += "\n"  # blank line between sections
        new_text = existing + section
        _atomic_write_text(target, new_text)
