"""System-prompt assembly: starter DNA + rolling evolution appendix.

The only public entry point is :func:`load_system_prompt`. It reads
``regions/<name>/prompt.md`` (immutable constitutional DNA written
once at region birth) and, if present and non-empty,
``regions/<name>/memory/appendices/rolling.md`` (append-only evolution
log maintained by :class:`region_template.appendix.AppendixStore`).

The two halves are joined with an explicit delimiter
(``# Evolution appendix``) so the LLM can distinguish "what I was
born with" from "what I've learned". Today the single call site is
``SleepCoordinator._review_events``; post-v0 handler-driven LLM calls
will use the same helper.
"""

from __future__ import annotations

from pathlib import Path

_APPENDIX_SUBPATH = Path("memory") / "appendices" / "rolling.md"
_DELIMITER = "\n\n---\n\n# Evolution appendix\n\n"


def load_system_prompt(region_root: Path) -> str:
    """Return the full system prompt for a region.

    Args:
        region_root: absolute path to ``regions/<name>/``.

    Returns:
        ``prompt.md`` content verbatim if no appendix exists or the
        appendix is empty; otherwise ``prompt.md`` + explicit
        delimiter + ``rolling.md`` content.
    """
    starter = (region_root / "prompt.md").read_text(encoding="utf-8")
    rolling_path = region_root / _APPENDIX_SUBPATH
    if not rolling_path.is_file():
        return starter
    rolling = rolling_path.read_text(encoding="utf-8")
    if not rolling.strip():
        return starter

    head = starter if starter.endswith("\n") else starter + "\n"
    return head + _DELIMITER.lstrip("\n") + rolling
