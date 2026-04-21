"""RegionReader sandboxed filesystem reader — unit tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from observatory.region_reader import RegionReader, SandboxError


def test_read_prompt_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    assert reader.read_prompt("testregion") == "# hello from testregion\n"


def test_read_stm_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    assert reader.read_stm("testregion") == {"note": "ok", "n": 3}


def test_read_subscriptions_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    subs = reader.read_subscriptions("testregion")
    assert subs == {"topics": ["hive/modulator/+", "hive/self/identity"]}


def test_unknown_region_returns_404(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_prompt("does-not-exist")
    assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_invalid_region_name_returns_404(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    for bad in ["../etc/passwd", "foo/bar", "foo bar", "foo.bar"]:
        with pytest.raises(SandboxError) as ei:
            reader.read_prompt(bad)
        assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_missing_file_returns_404(regions_root: Path) -> None:
    # make a region with no prompt.md
    empty = regions_root / "emptyregion"
    empty.mkdir()
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_prompt("emptyregion")
    assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_oversize_returns_413(regions_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("observatory.region_reader.MAX_FILE_BYTES", 8)
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_prompt("testregion")
    assert ei.value.code == 413  # noqa: PLR2004 — HTTP status under test


def test_parse_error_returns_502(regions_root: Path) -> None:
    (regions_root / "testregion" / "memory" / "stm.json").write_text(
        "not-json{", encoding="utf-8"
    )
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_stm("testregion")
    assert ei.value.code == 502  # noqa: PLR2004 — HTTP status under test


@pytest.mark.skipif(
    os.name == "nt" and not hasattr(os, "symlink"),
    reason="symlink privilege on Windows may be absent",
)
def test_symlink_rejected(regions_root: Path) -> None:
    outside = regions_root.parent / "secrets.txt"
    outside.write_text("nuclear codes", encoding="utf-8")
    link = regions_root / "testregion" / "prompt.md"
    link.unlink()
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable in this environment")
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_prompt("testregion")
    assert ei.value.code == 403  # noqa: PLR2004 — HTTP status under test
