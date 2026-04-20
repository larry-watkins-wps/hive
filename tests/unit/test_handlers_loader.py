"""Tests for region_template.handlers_loader — spec §A.6.1, §A.6.3, §A.6.4."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from region_template.errors import ConfigError
from region_template.handlers_loader import (
    HandlerModule,
    discover,
    match_handlers_for_topic,
)

# ---------------------------------------------------------------------------
# Constants used in assertions (silences ruff PLR2004 on "magic values").
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 30.0
_CUSTOM_TIMEOUT_S = 10.0
_OVERLAPPING_WILDCARD_COUNT = 2


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_HANDLE_STUB = """async def handle(envelope, ctx):
    return None
"""


def _write_handler(
    dir_: Path,
    name: str,
    *,
    subscriptions: list[str] | None | str = None,
    extras: str = "",
    body: str = _HANDLE_STUB,
) -> Path:
    """Write a handler file. ``subscriptions`` may be a list, None, or raw str.

    - ``None`` means the SUBSCRIPTIONS line is omitted entirely.
    - ``list`` renders as ``SUBSCRIPTIONS = [...]``.
    - ``str`` is written verbatim (e.g. for intentionally bad types).
    """
    lines: list[str] = []
    if subscriptions is not None:
        if isinstance(subscriptions, list):
            lines.append(f"SUBSCRIPTIONS = {subscriptions!r}")
        else:
            lines.append(f"SUBSCRIPTIONS = {subscriptions}")
    if extras:
        lines.append(extras)
    lines.append(body)
    path = dir_ / f"{name}.py"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# discover() — base cases
# ---------------------------------------------------------------------------


class TestDiscoverEmpty:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        assert discover(tmp_path) == []

    def test_only_init_py_returns_empty_list(self, tmp_path: Path) -> None:
        (tmp_path / "__init__.py").write_text("# package marker\n", encoding="utf-8")
        assert discover(tmp_path) == []

    def test_missing_directory_returns_empty_list(self, tmp_path: Path) -> None:
        """A region without a handlers/ directory is legal (zero handlers)."""
        missing = tmp_path / "does_not_exist"
        assert discover(missing) == []


# ---------------------------------------------------------------------------
# discover() — module-constant reading
# ---------------------------------------------------------------------------


class TestDiscoverDefaults:
    def test_single_handler_minimal_defaults(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "on_text", subscriptions=["hive/sensory/auditory/text"])
        mods = discover(tmp_path)
        assert len(mods) == 1
        m = mods[0]
        assert isinstance(m, HandlerModule)
        assert m.name == "on_text"
        assert m.path.name == "on_text.py"
        assert m.subscriptions == ("hive/sensory/auditory/text",)
        assert m.timeout_s == _DEFAULT_TIMEOUT_S
        assert m.qos == 1
        assert m.on_heartbeat is False
        assert m.requires_capability == ()
        assert asyncio.iscoroutinefunction(m.handle)

    def test_optional_constants_honored(self, tmp_path: Path) -> None:
        _write_handler(
            tmp_path,
            "on_audio",
            subscriptions=["hive/sensory/auditory/text"],
            extras=(
                "TIMEOUT_S = 10\n"
                "QOS = 0\n"
                "ON_HEARTBEAT = True\n"
                "REQUIRES_CAPABILITY = ['self_modify']\n"
            ),
        )
        mods = discover(tmp_path)
        assert len(mods) == 1
        m = mods[0]
        assert m.timeout_s == _CUSTOM_TIMEOUT_S
        assert m.qos == 0
        assert m.on_heartbeat is True
        assert m.requires_capability == ("self_modify",)

    def test_requires_capability_string_accepted_as_single_element(
        self, tmp_path: Path
    ) -> None:
        """Per spec table REQUIRES_CAPABILITY is list[str]; we normalize a bare
        string into a one-element tuple for author-friendliness (matches the
        plan prose typo). Empty string stays empty tuple."""
        _write_handler(
            tmp_path,
            "on_x",
            subscriptions=["hive/a/b"],
            extras="REQUIRES_CAPABILITY = 'self_modify'\n",
        )
        mods = discover(tmp_path)
        assert len(mods) == 1
        assert mods[0].requires_capability == ("self_modify",)


# ---------------------------------------------------------------------------
# discover() — skip / error paths
# ---------------------------------------------------------------------------


class TestDiscoverSkips:
    def test_missing_subscriptions_warns_and_skips(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "no_subs", subscriptions=None)
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        warns = [e for e in logs if e.get("log_level") in ("warn", "warning")]
        assert any("SUBSCRIPTIONS" in (e.get("event") or "") for e in warns)

    def test_empty_subscriptions_list_warns_and_skips(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "empty_subs", subscriptions=[])
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        warns = [e for e in logs if e.get("log_level") in ("warn", "warning")]
        assert len(warns) >= 1

    def test_non_list_subscriptions_warns_and_skips(self, tmp_path: Path) -> None:
        # SUBSCRIPTIONS = "hive/foo"  (a string, not a list)
        _write_handler(tmp_path, "scalar_subs", subscriptions='"hive/foo"')
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        warns = [e for e in logs if e.get("log_level") in ("warn", "warning")]
        assert len(warns) >= 1

    def test_non_async_handle_errors_and_skips(self, tmp_path: Path) -> None:
        _write_handler(
            tmp_path,
            "sync_handle",
            subscriptions=["hive/a/b"],
            body="def handle(envelope, ctx):\n    return None\n",
        )
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        errs = [e for e in logs if e.get("log_level") == "error"]
        assert len(errs) >= 1

    def test_missing_handle_errors_and_skips(self, tmp_path: Path) -> None:
        _write_handler(
            tmp_path,
            "no_handle",
            subscriptions=["hive/a/b"],
            body="# no handle defined\n",
        )
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        errs = [e for e in logs if e.get("log_level") == "error"]
        assert len(errs) >= 1

    def test_syntax_error_logged_and_skipped(self, tmp_path: Path) -> None:
        """Per §A.6.3: import failures are logged as ERROR; region still boots."""
        (tmp_path / "broken.py").write_text(
            "this is not valid python )(\n", encoding="utf-8"
        )
        with capture_logs() as logs:
            mods = discover(tmp_path)
        assert mods == []
        errs = [e for e in logs if e.get("log_level") == "error"]
        assert len(errs) >= 1

    def test_broken_file_does_not_prevent_valid_one(self, tmp_path: Path) -> None:
        """One bad apple does not spoil the bunch."""
        (tmp_path / "broken.py").write_text("nope nope )(\n", encoding="utf-8")
        _write_handler(tmp_path, "ok", subscriptions=["hive/a/b"])
        mods = discover(tmp_path)
        assert len(mods) == 1
        assert mods[0].name == "ok"


# ---------------------------------------------------------------------------
# discover() — recursion / duplicates
# ---------------------------------------------------------------------------


class TestDiscoverStructure:
    def test_no_recursion_into_subdirs(self, tmp_path: Path) -> None:
        """Only direct-child .py files are considered (§A.6.3)."""
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_handler(sub, "nested", subscriptions=["hive/a/b"])
        _write_handler(tmp_path, "direct", subscriptions=["hive/c/d"])
        mods = discover(tmp_path)
        assert [m.name for m in mods] == ["direct"]

    def test_duplicate_exact_topic_raises_config_error(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "a", subscriptions=["hive/sensory/auditory/text"])
        _write_handler(tmp_path, "b", subscriptions=["hive/sensory/auditory/text"])
        with pytest.raises(ConfigError) as exc:
            discover(tmp_path)
        msg = str(exc.value)
        assert "hive/sensory/auditory/text" in msg
        assert "a" in msg and "b" in msg

    def test_overlapping_wildcards_are_allowed(self, tmp_path: Path) -> None:
        """Two handlers may both listen on `hive/cognitive/+/query` — spec
        only forbids duplicate EXACT topic filters."""
        _write_handler(tmp_path, "alpha", subscriptions=["hive/cognitive/+/query"])
        _write_handler(tmp_path, "beta", subscriptions=["hive/cognitive/+/query"])
        mods = discover(tmp_path)
        assert len(mods) == _OVERLAPPING_WILDCARD_COUNT
        assert {m.name for m in mods} == {"alpha", "beta"}

    def test_filename_sort_is_alphabetical(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "c", subscriptions=["hive/a/1"])
        _write_handler(tmp_path, "a", subscriptions=["hive/a/2"])
        _write_handler(tmp_path, "b", subscriptions=["hive/a/3"])
        mods = discover(tmp_path)
        assert [m.name for m in mods] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# HandlerModule.has_wildcard
# ---------------------------------------------------------------------------


class TestHasWildcard:
    def test_false_when_all_exact(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "h", subscriptions=["hive/a/b", "hive/c/d"])
        mods = discover(tmp_path)
        assert mods[0].has_wildcard is False

    def test_true_when_plus(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "h", subscriptions=["hive/a/+/x"])
        mods = discover(tmp_path)
        assert mods[0].has_wildcard is True

    def test_true_when_hash(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "h", subscriptions=["hive/a/#"])
        mods = discover(tmp_path)
        assert mods[0].has_wildcard is True


# ---------------------------------------------------------------------------
# match_handlers_for_topic — §A.6.4 dispatch order
# ---------------------------------------------------------------------------


class TestMatchHandlersForTopic:
    def test_single_exact_before_two_wildcards(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "exact_b", subscriptions=["hive/modulator/cortisol"])
        _write_handler(tmp_path, "wild_a", subscriptions=["hive/modulator/#"])
        _write_handler(tmp_path, "wild_c", subscriptions=["hive/modulator/+"])
        _write_handler(tmp_path, "unrelated", subscriptions=["hive/sensory/visual/processed"])

        mods = discover(tmp_path)
        matched = match_handlers_for_topic(mods, "hive/modulator/cortisol")
        assert [m.name for m in matched] == ["exact_b", "wild_a", "wild_c"]

    def test_no_matches_returns_empty_list(self, tmp_path: Path) -> None:
        _write_handler(tmp_path, "h", subscriptions=["hive/a/b"])
        mods = discover(tmp_path)
        assert match_handlers_for_topic(mods, "hive/x/y") == []

    def test_handler_with_mixed_exact_and_wildcard_treated_by_match_kind(
        self, tmp_path: Path
    ) -> None:
        """A module whose matching filter for this topic is exact counts as
        exact for this topic; a module whose only matching filter is a
        wildcard counts as wildcard."""
        # "both" has BOTH an exact match and a wildcard in SUBSCRIPTIONS —
        # for topic hive/modulator/cortisol, the exact filter matches, so
        # it's exact-tier for THIS topic.
        _write_handler(
            tmp_path,
            "both",
            subscriptions=["hive/modulator/cortisol", "hive/sensory/+"],
        )
        _write_handler(tmp_path, "wild", subscriptions=["hive/modulator/#"])
        mods = discover(tmp_path)
        matched = match_handlers_for_topic(mods, "hive/modulator/cortisol")
        # "both" matches exactly (because one of its filters is exact on the
        # topic); "wild" matches only via wildcard. Exact-first, alphabetical.
        assert [m.name for m in matched] == ["both", "wild"]

    def test_alphabetical_within_exact_tier(self, tmp_path: Path) -> None:
        # Multiple wildcard filters can match one topic from different handlers
        # without duplication. Use two handlers with different wildcard filters
        # that both match the same topic to exercise within-wildcard ordering.
        _write_handler(tmp_path, "z_wild", subscriptions=["hive/a/+"])
        _write_handler(tmp_path, "a_wild", subscriptions=["hive/a/#"])
        mods = discover(tmp_path)
        matched = match_handlers_for_topic(mods, "hive/a/b")
        assert [m.name for m in matched] == ["a_wild", "z_wild"]
