"""Unit tests for :mod:`region_template.prompt_assembly`.

``load_system_prompt`` concatenates a region's immutable starter
prompt (``prompt.md``) with its append-only evolution appendix
(``memory/appendices/rolling.md``) using an explicit delimiter so the
LLM can tell "what I was born with" from "what I've learned".
"""

from __future__ import annotations

from pathlib import Path

from region_template.prompt_assembly import load_system_prompt


def _make_region(tmp_path: Path, *, starter: str, rolling: str | None) -> Path:
    root = tmp_path / "regions" / "test_region"
    root.mkdir(parents=True)
    (root / "prompt.md").write_text(starter, encoding="utf-8")
    if rolling is not None:
        appendix_dir = root / "memory" / "appendices"
        appendix_dir.mkdir(parents=True)
        (appendix_dir / "rolling.md").write_text(rolling, encoding="utf-8")
    return root


def test_returns_starter_verbatim_when_no_appendix(tmp_path: Path) -> None:
    starter = "You are the test region.\n\nBe curious.\n"
    root = _make_region(tmp_path, starter=starter, rolling=None)
    assert load_system_prompt(root) == starter


def test_concatenates_with_explicit_delimiter(tmp_path: Path) -> None:
    starter = "You are the test region.\n"
    rolling = "## 2026-04-22T03:14:00+00:00 — quiet_window\n\nFirst insight.\n"
    root = _make_region(tmp_path, starter=starter, rolling=rolling)

    out = load_system_prompt(root)
    assert out.startswith(starter)
    assert "# Evolution appendix" in out
    assert out.endswith(rolling) or out.endswith(rolling.rstrip() + "\n")
    # The starter must appear before the delimiter, and the delimiter
    # before the appendix content, so the LLM reads them in order.
    assert out.index(starter) < out.index("# Evolution appendix")
    assert out.index("# Evolution appendix") < out.index("First insight.")


def test_empty_appendix_file_is_treated_as_absent(tmp_path: Path) -> None:
    starter = "You are the test region.\n"
    root = _make_region(tmp_path, starter=starter, rolling="")
    assert load_system_prompt(root) == starter
