"""Integration tests for ``tools/dbg/hive_stm.py``.

Task 7.3, per spec §H.3 (operator-side filesystem peek at STM). Uses a
``tmp_path`` regions tree and ``--root`` to pin the walker, so no real
``regions/`` directory is required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tools.dbg.hive_stm import app

pytestmark = pytest.mark.integration

# Named exit codes — keep ruff PLR2004 quiet on "magic values".
EXIT_OK = 0
EXIT_DATA_ERR = 1
EXIT_USAGE = 2
LIMIT = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stm(
    root: Path,
    region: str,
    *,
    slots: dict | None = None,
    events: list | None = None,
    schema_version: int | None = 1,
    include_region: bool = True,
    raw_text: str | None = None,
) -> Path:
    """Write a minimal stm.json at ``<root>/regions/<region>/memory/stm.json``."""
    path = root / "regions" / region / "memory" / "stm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    payload: dict = {
        "updated_at": "2026-04-19T10:30:00.000Z",
        "slots": slots if slots is not None else {},
        "recent_events": events if events is not None else [],
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version
    if include_region:
        payload["region"] = region
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_populated_stm_renders_slots_and_events(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        slots={
            "current_task": "writing phase 7 tools",
            "attention_focus": "hive_stm",
            "mood": "focused",
        },
        events=[
            {
                "topic": "hive/sensory/input/text",
                "content": "hello world",
            },
            {"topic": "hive/motor/output", "data": "reply"},
        ],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert "region:" in result.stdout
    assert "test_region" in result.stdout
    assert "current_task" in result.stdout
    assert "attention_focus" in result.stdout
    assert "hive/sensory/input/text" in result.stdout
    assert "recent events" in result.stdout.lower()


def test_raw_flag_emits_round_trippable_json(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        slots={"mood": "focused"},
        events=[{"topic": "hive/x", "content": "y"}],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path), "--raw"]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["region"] == "test_region"
    assert parsed["slots"] == {"mood": "focused"}


def test_slots_only_omits_events_section(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        slots={"mood": "focused"},
        events=[{"topic": "hive/x"}],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path), "--slots-only"]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert "mood" in result.stdout
    assert "recent events" not in result.stdout.lower()


def test_events_only_omits_slots_header(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        slots={"mood": "focused"},
        events=[{"topic": "hive/x"}],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path), "--events-only"]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert "recent events" in result.stdout.lower()
    assert "slots (" not in result.stdout


def test_limit_caps_event_count(tmp_path: Path) -> None:
    events = [{"topic": f"hive/topic/{i}", "content": f"msg{i}"} for i in range(10)]
    _make_stm(tmp_path, "test_region", events=events)
    result = _runner().invoke(
        app,
        ["test_region", "--root", str(tmp_path), "--limit", str(LIMIT)],
    )
    assert result.exit_code == EXIT_OK, result.stderr
    # Exactly LIMIT event lines should be printed (the last LIMIT entries).
    shown = [i for i in range(10) if f"hive/topic/{i}" in result.stdout]
    assert len(shown) == LIMIT
    assert shown == [5, 6, 7, 8, 9]


def test_missing_file_exits_usage_with_path_hint(tmp_path: Path) -> None:
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_USAGE
    # Path or --root hint should surface on stderr.
    combined = result.stderr.lower()
    assert "stm.json" in combined or "not found" in combined
    assert "--root" in result.stderr


def test_malformed_json_exits_data_err(tmp_path: Path) -> None:
    _make_stm(tmp_path, "test_region", raw_text="{ not json ]")
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_DATA_ERR
    assert "malformed" in result.stderr.lower() or "invalid" in result.stderr.lower()


def test_traversal_region_name_rejected(tmp_path: Path) -> None:
    result = _runner().invoke(
        app, ["../evil", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_USAGE
    assert "region" in result.stderr.lower()


def test_missing_schema_version_degrades_gracefully(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        slots={"mood": "focused"},
        events=[{"topic": "hive/x"}],
        schema_version=None,
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_OK
    # Warning should surface on stderr, but body still prints.
    assert "schema_version" in result.stderr.lower() or "warning" in result.stderr.lower()
    assert "mood" in result.stdout


def test_event_without_topic_uses_json_preview(tmp_path: Path) -> None:
    _make_stm(
        tmp_path,
        "test_region",
        events=[{"type": "tick", "seq": 42}],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path)]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert "tick" in result.stdout or "seq" in result.stdout


def _can_symlink(tmp_path: Path) -> bool:
    """Probe whether the current process can create filesystem symlinks.

    On Windows, ``os.symlink`` requires Developer Mode or admin; on POSIX
    it's always permitted. Probing is safer than hard-coding the platform
    check because CI runners vary.
    """
    target = tmp_path / "_symlink_probe_target"
    link = tmp_path / "_symlink_probe_link"
    target.write_text("x", encoding="utf-8")
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return False
    finally:
        link.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
    return True


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """F8: a symlinked stm.json pointing outside the regions tree must be rejected."""
    if not _can_symlink(tmp_path):
        pytest.skip(
            "symlink creation not permitted on this system "
            "(Windows requires Developer Mode or admin)."
        )

    # Real stm.json OUTSIDE the regions tree.
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    real_stm = outside_dir / "stm.json"
    real_stm.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "region": "test_region",
                "updated_at": "2026-04-19T10:30:00.000Z",
                "slots": {},
                "recent_events": [],
            }
        ),
        encoding="utf-8",
    )

    # Place a symlink inside the regions tree pointing at the outside file.
    link_dir = tmp_path / "regions" / "test_region" / "memory"
    link_dir.mkdir(parents=True)
    link_path = link_dir / "stm.json"
    os.symlink(real_stm, link_path)

    result = _runner().invoke(app, ["test_region", "--root", str(tmp_path)])
    assert result.exit_code == EXIT_USAGE, result.stderr
    combined = result.stderr.lower()
    assert "unsafe" in combined or "outside" in combined


def test_malformed_slots_type_degrades_with_warning(tmp_path: Path) -> None:
    """F9: non-dict 'slots' triggers a warning on stderr but still renders."""
    path = tmp_path / "regions" / "test_region" / "memory" / "stm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "region": "test_region",
                "updated_at": "2026-04-19T10:30:00.000Z",
                "slots": [],  # WRONG TYPE — should be dict.
                "recent_events": [],
            }
        ),
        encoding="utf-8",
    )
    result = _runner().invoke(app, ["test_region", "--root", str(tmp_path)])
    assert result.exit_code == EXIT_OK, result.stderr
    assert "warning" in result.stderr.lower()
    assert "slots" in result.stderr.lower()
    # Still renders the (empty) slots section.
    assert "slots (0)" in result.stdout


def test_limit_zero_renders_empty_events_section(tmp_path: Path) -> None:
    """F10: --limit 0 prints the events header with zero events listed."""
    _make_stm(
        tmp_path,
        "test_region",
        events=[{"topic": "hive/x", "content": "y"}],
    )
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path), "--limit", "0"]
    )
    assert result.exit_code == EXIT_OK, result.stderr
    assert "recent events (last 0 of 1)" in result.stdout
    # The event itself must NOT appear in the output.
    assert "hive/x" not in result.stdout


def test_negative_limit_rejected(tmp_path: Path) -> None:
    """F10: --limit -1 exits EXIT_USAGE with an explanatory message."""
    _make_stm(tmp_path, "test_region")
    result = _runner().invoke(
        app, ["test_region", "--root", str(tmp_path), "--limit", "-1"]
    )
    assert result.exit_code == EXIT_USAGE
    assert "--limit" in result.stderr or "limit" in result.stderr.lower()
