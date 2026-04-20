"""Tests for region_template.git_tools — spec §D.5.7.

Covers the per-region ``GitTools`` wrapper around ``subprocess`` ``git``:
  * ``_ensure_repo`` bootstraps a repo + initial commit on a fresh directory.
  * ``_ensure_repo`` is a no-op on an already-initialised repo.
  * ``status_clean`` returns ``True`` on a clean tree, ``False`` when dirty.
  * ``commit_all`` stages all + commits; returns ``CommitResult`` with a
    40-char sha.
  * ``commit_all`` on a clean tree raises ``GitError`` (empty commits are
    rejected — the spec's ``--allow-empty=never`` is not a valid flag; git's
    default behaviour already rejects empty commits).
  * ``revert_to`` rewinds working tree to the given sha (spec §D.5.7 +
    §D.8 — uses ``git reset --hard``; plan's "revert commit" phrasing is
    a misnomer).
  * ``last_good_sha`` returns ``git rev-parse HEAD^`` (parent of HEAD).
  * ``GitError`` is raised on any failing subprocess call.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from region_template.errors import GitError
from region_template.git_tools import CommitResult, GitTools

_SHA_RE_LEN = 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _head_sha(root: Path) -> str:
    """Return the current HEAD sha of ``root``."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _make_root(tmp_path: Path, name: str = "region_foo") -> Path:
    """Create ``tmp_path/<name>`` and return it (parent exists, ``.git`` absent)."""
    root = tmp_path / name
    root.mkdir()
    # Drop one untracked file so the initial commit has content.
    (root / "README.txt").write_text("hello", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Construction / _ensure_repo
# ---------------------------------------------------------------------------

def test_ensure_repo_creates_git_dir(tmp_path: Path) -> None:
    """Fresh directory gets a ``.git`` subdir after construction."""
    root = _make_root(tmp_path)
    GitTools(root, region_name="foo")
    assert (root / ".git").is_dir()


def test_ensure_repo_makes_initial_commit(tmp_path: Path) -> None:
    """Initial commit exists on a fresh repo."""
    root = _make_root(tmp_path)
    GitTools(root, region_name="foo")
    sha = _head_sha(root)
    assert len(sha) == _SHA_RE_LEN


def test_ensure_repo_no_op_on_existing_repo(tmp_path: Path) -> None:
    """Second ``GitTools`` on the same root reuses the existing repo."""
    root = _make_root(tmp_path)
    GitTools(root, region_name="foo")
    first_sha = _head_sha(root)
    # Second construction must not re-init or add a new commit.
    GitTools(root, region_name="foo")
    assert _head_sha(root) == first_sha


def test_ensure_repo_missing_root_raises(tmp_path: Path) -> None:
    """Construction on a non-existent directory raises ``GitError``."""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(GitError):
        GitTools(missing, region_name="foo")


def test_ensure_repo_sets_user_name_and_email(tmp_path: Path) -> None:
    """User name + email are set to the region name on init."""
    root = _make_root(tmp_path, name="region_bar")
    GitTools(root, region_name="bar")
    name = subprocess.run(
        ["git", "config", "user.name"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "user.email"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert name == "bar"
    assert email == "bar@hive.local"


# ---------------------------------------------------------------------------
# status_clean
# ---------------------------------------------------------------------------

def test_status_clean_true_after_init(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    assert tools.status_clean() is True


def test_status_clean_false_when_untracked_present(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    (root / "new.txt").write_text("x", encoding="utf-8")
    assert tools.status_clean() is False


def test_status_clean_false_when_tracked_modified(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    (root / "README.txt").write_text("changed", encoding="utf-8")
    assert tools.status_clean() is False


# ---------------------------------------------------------------------------
# commit_all
# ---------------------------------------------------------------------------

def test_commit_all_returns_commit_result_with_sha(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    (root / "data.txt").write_text("v1", encoding="utf-8")
    result = tools.commit_all("add data")
    assert isinstance(result, CommitResult)
    assert len(result.sha) == _SHA_RE_LEN


def test_commit_all_advances_head(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    before = _head_sha(root)
    (root / "data.txt").write_text("v1", encoding="utf-8")
    result = tools.commit_all("add data")
    after = _head_sha(root)
    assert result.sha == after
    assert before != after


def test_commit_all_clean_tree_raises_git_error(tmp_path: Path) -> None:
    """Empty commits are rejected by git's default behaviour → GitError.

    Spec's ``--allow-empty=never`` flag is not valid git CLI; git rejects
    empty commits by default with a non-zero exit code.
    """
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    assert tools.status_clean() is True
    with pytest.raises(GitError):
        tools.commit_all("nothing to commit")


def test_commit_all_leaves_tree_clean(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    (root / "data.txt").write_text("v1", encoding="utf-8")
    tools.commit_all("add data")
    assert tools.status_clean() is True


# ---------------------------------------------------------------------------
# revert_to
# ---------------------------------------------------------------------------

def test_revert_to_rewinds_to_sha(tmp_path: Path) -> None:
    """``revert_to(sha)`` resets the working tree and HEAD to ``sha``."""
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    original = _head_sha(root)
    (root / "data.txt").write_text("v1", encoding="utf-8")
    tools.commit_all("add data")
    assert (root / "data.txt").exists()
    tools.revert_to(original)
    assert _head_sha(root) == original
    assert not (root / "data.txt").exists()


def test_revert_to_clean_afterwards(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    original = _head_sha(root)
    (root / "data.txt").write_text("v1", encoding="utf-8")
    tools.commit_all("add data")
    tools.revert_to(original)
    assert tools.status_clean() is True


def test_revert_to_bad_sha_raises(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    with pytest.raises(GitError):
        tools.revert_to("deadbeef" * 5)  # 40-char non-existent sha


# ---------------------------------------------------------------------------
# last_good_sha
# ---------------------------------------------------------------------------

def test_last_good_sha_returns_parent(tmp_path: Path) -> None:
    """``last_good_sha()`` resolves ``HEAD^`` — the parent of HEAD."""
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    initial = _head_sha(root)
    (root / "data.txt").write_text("v1", encoding="utf-8")
    tools.commit_all("add data")
    assert tools.last_good_sha() == initial


def test_last_good_sha_on_single_commit_raises(tmp_path: Path) -> None:
    """HEAD^ does not exist when repo has only the initial commit → GitError."""
    root = _make_root(tmp_path)
    tools = GitTools(root, region_name="foo")
    with pytest.raises(GitError):
        tools.last_good_sha()


# ---------------------------------------------------------------------------
# CommitResult dataclass
# ---------------------------------------------------------------------------

def test_commit_result_is_frozen() -> None:
    result = CommitResult(sha="a" * 40)
    with pytest.raises(Exception):  # noqa: B017 — dataclass frozen raises FrozenInstanceError
        result.sha = "b" * 40  # type: ignore[misc]


def test_commit_result_sha_field() -> None:
    result = CommitResult(sha="abc123")
    assert result.sha == "abc123"
