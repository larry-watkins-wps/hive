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


def test_read_config_redacts_secrets(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    cfg = reader.read_config("testregion")
    assert cfg["name"] == "testregion"
    assert cfg["llm_model"] == "fake-1.0"
    assert cfg["api_key"] == "***"
    # Nested under a dict
    assert cfg["nested"]["auth_token"] == "***"
    # Nested under a list — spec says "Nested dicts are walked; lists of dicts too."
    # aws_secret is a list of scalars here: the top-level key ends `_secret` so the
    # entire value is redacted to "***".
    assert cfg["nested"]["aws_secret"] == "***"


def test_read_config_list_of_dicts_recurses(regions_root: Path) -> None:
    """Spec §6.1 promises 'lists of dicts too'. Verify inner dicts with secret
    keys inside a non-secret-keyed list are still walked and redacted."""
    (regions_root / "testregion" / "config.yaml").write_text(
        "upstreams:\n"
        "  - name: primary\n"
        "    api_key: live-key-1\n"
        "  - name: backup\n"
        "    auth_token: live-token-2\n",
        encoding="utf-8",
    )
    reader = RegionReader(regions_root)
    cfg = reader.read_config("testregion")
    assert cfg["upstreams"][0] == {"name": "primary", "api_key": "***"}
    assert cfg["upstreams"][1] == {"name": "backup", "auth_token": "***"}


def test_read_config_case_insensitive_suffix(regions_root: Path) -> None:
    (regions_root / "testregion" / "config.yaml").write_text(
        "Session_Key: abc\nSESSION_KEY: def\napi_password: ok\n", encoding="utf-8",
    )
    reader = RegionReader(regions_root)
    cfg = reader.read_config("testregion")
    assert cfg["Session_Key"] == "***"
    assert cfg["SESSION_KEY"] == "***"
    # api_password does not match any _SECRET_SUFFIXES — left alone
    assert cfg["api_password"] == "ok"


def test_list_handlers_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    entries = reader.list_handlers("testregion")
    assert len(entries) == 1
    assert entries[0].path == "handlers/on_wake.py"
    assert entries[0].size > 0


def test_list_handlers_missing_dir_returns_empty(regions_root: Path) -> None:
    (regions_root / "testregion" / "handlers" / "on_wake.py").unlink()
    (regions_root / "testregion" / "handlers").rmdir()
    reader = RegionReader(regions_root)
    assert reader.list_handlers("testregion") == []


def test_list_handlers_is_sorted(regions_root: Path) -> None:
    base = regions_root / "testregion" / "handlers"
    (base / "a.py").write_text("", encoding="utf-8")
    (base / "sub").mkdir()
    (base / "sub" / "b.py").write_text("", encoding="utf-8")
    reader = RegionReader(regions_root)
    paths = [e.path for e in reader.list_handlers("testregion")]
    assert paths == sorted(paths)
    assert "handlers/a.py" in paths
    assert "handlers/sub/b.py" in paths


def test_list_handlers_works_without_pathlib_walk(
    regions_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pathlib.Path.walk`` landed in Python 3.12. The observatory's
    container runs Python 3.11 (observatory/pyproject.toml declares
    ``requires-python = ">=3.11"``), so the implementation must not rely
    on it. Simulate 3.11 by removing the attribute and confirm handlers
    still list correctly."""
    import pathlib  # noqa: PLC0415 — scoped here so the delattr only affects this test

    base = regions_root / "testregion" / "handlers"
    (base / "sub").mkdir()
    (base / "sub" / "deep.py").write_text("", encoding="utf-8")

    monkeypatch.delattr(pathlib.Path, "walk", raising=False)
    monkeypatch.delattr(pathlib.PurePath, "walk", raising=False)

    reader = RegionReader(regions_root)
    paths = [e.path for e in reader.list_handlers("testregion")]
    assert "handlers/on_wake.py" in paths
    assert "handlers/sub/deep.py" in paths


def test_read_appendix_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    appendix_dir = regions_root / "testregion" / "memory" / "appendices"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    (appendix_dir / "rolling.md").write_text(
        "## 2026-04-22T10:00:00Z - sleep\n\nLearned that topic X ...\n",
        encoding="utf-8",
    )
    assert "topic X" in reader.read_appendix("testregion")


def test_read_appendix_missing_returns_none(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    assert reader.read_appendix("testregion") is None


def test_read_appendix_invalid_region_name_returns_404(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_appendix("../evil")
    assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_read_appendix_oversize_returns_413(
    regions_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appendix_dir = regions_root / "testregion" / "memory" / "appendices"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    (appendix_dir / "rolling.md").write_text("aaaa", encoding="utf-8")
    monkeypatch.setattr("observatory.region_reader.MAX_FILE_BYTES", 2)
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_appendix("testregion")
    assert ei.value.code == 413  # noqa: PLR2004 — HTTP status under test
