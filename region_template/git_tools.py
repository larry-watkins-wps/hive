"""Per-region git integration — spec §D.5.7.

Every Hive region owns a local git repository at its root. ``GitTools`` wraps
the subset of ``git`` operations the runtime needs (init, status, commit-all,
hard reset, parent-of-HEAD lookup) as subprocess calls. No remotes; nothing
ever pushes.

All git failures surface as ``GitError`` (spec §A.7.6, §D.8).

Deviations from the spec prose — see also the commit message:

* ``revert_to`` uses ``git reset --hard``. Spec §D.5.7's code block writes
  ``run(["git", "reset", "--hard", sha], cwd=self._root)`` and §D.8 explicitly
  states rollback uses ``git reset --hard HEAD~1``. The method name
  ``revert_to`` is a misnomer; we follow the behaviour the spec prescribes,
  not the label.
* ``last_good_sha`` returns ``git rev-parse HEAD^`` (parent of HEAD) per the
  spec docstring. There is no "boot-successful" tracking in this module.
* ``commit_all`` does NOT pass ``--allow-empty=never`` — that is not a valid
  git CLI flag. Git rejects empty commits by default; the non-zero exit
  propagates through ``_run`` as ``GitError``.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess

from region_template.errors import GitError

# Minimum argv length required to form a "<git> <subcommand>" error prefix
# (e.g. "git status"). Below this we fall back to argv[0] verbatim.
_MIN_ARGV_FOR_SUBCOMMAND = 2


@dataclass(frozen=True)
class CommitResult:
    """Result of ``GitTools.commit_all``. Minimal v0 surface — just the sha."""

    sha: str


class GitTools:
    """Wraps ``git`` CLI operations scoped to a region's root directory."""

    def __init__(self, root: Path, region_name: str) -> None:
        self._root = Path(root)
        self._region_name = region_name
        self._ensure_repo()

    # ------------------------------------------------------------------
    # Repo bootstrap
    # ------------------------------------------------------------------
    def _ensure_repo(self) -> None:
        """Initialise a repo + initial commit if ``.git`` is absent.

        A repo is deemed initialised when ``<root>/.git`` exists. If it's
        missing we ``git init``, set ``user.name`` / ``user.email`` scoped
        to the region, then stage all current contents and make an
        ``initial region state`` commit. If the initial tree is empty we
        still need a root commit so ``HEAD`` resolves — ``--allow-empty``
        is passed for that single call only.
        """
        if (self._root / ".git").exists():
            return
        self._run(["git", "init"])
        self._run(["git", "config", "user.name", self._region_name])
        self._run(
            ["git", "config", "user.email", f"{self._region_name}@hive.local"]
        )
        self._run(["git", "add", "."])
        # The working tree might be empty on a brand-new region; use
        # --allow-empty ONLY for this bootstrap commit so the repo has a
        # valid HEAD to revert_to / diff against. Subsequent commit_all
        # calls deliberately omit the flag so empty commits fail loudly.
        self._run(["git", "commit", "--allow-empty", "-m", "initial region state"])

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def status_clean(self) -> bool:
        """Return ``True`` iff the working tree has no changes (tracked or not)."""
        result = self._run(["git", "status", "--porcelain"], check=False)
        if result.returncode != 0:
            raise GitError(
                f"git status failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip() == ""

    # ------------------------------------------------------------------
    # Commit / revert / lookup
    # ------------------------------------------------------------------
    def commit_all(self, message: str) -> CommitResult:
        """Stage all changes and create a commit; return its sha.

        Raises ``GitError`` if there is nothing to commit (git's default
        behaviour rejects empty commits).
        """
        self._run(["git", "add", "-A"])
        self._run(["git", "commit", "-m", message])
        sha = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        return CommitResult(sha=sha)

    def revert_to(self, sha: str) -> None:
        """Hard-reset the working tree + HEAD to ``sha`` (spec §D.5.7 / §D.8)."""
        self._run(["git", "reset", "--hard", sha])

    def last_good_sha(self) -> str:
        """Return ``HEAD^`` — the parent of the current commit (spec §D.5.7).

        Used by glia rollback. Raises ``GitError`` if HEAD has no parent
        (only the initial commit exists).
        """
        return self._run(["git", "rev-parse", "HEAD^"]).stdout.strip()

    def current_head_sha(self) -> str:
        """Return ``HEAD`` — the sha of the current commit.

        Used by :mod:`region_template.self_modify` to check whether the
        region has committed any change since bootstrap before
        requesting a restart (spec §A.7.6).
        """
        return self._run(["git", "rev-parse", "HEAD"]).stdout.strip()

    # ------------------------------------------------------------------
    # Subprocess helper
    # ------------------------------------------------------------------
    def _run(
        self,
        argv: list[str],
        *,
        check: bool = True,
    ) -> CompletedProcess[str]:
        """Run ``argv`` in the region root and capture output.

        If ``check`` is true (default), a non-zero exit raises ``GitError``
        with the subcommand + stderr. Callers that need to branch on the
        exit code (``status_clean``) pass ``check=False`` and inspect
        ``result.returncode`` themselves.
        """
        try:
            result = subprocess.run(
                argv,
                cwd=self._root,
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            # cwd doesn't exist, or `git` binary missing from PATH.
            raise GitError(f"git {' '.join(argv[:2])} failed: {exc}") from exc
        except OSError as exc:
            raise GitError(f"git {' '.join(argv[:2])} failed: {exc}") from exc
        if check and result.returncode != 0:
            subcmd = (
                " ".join(argv[:2])
                if len(argv) >= _MIN_ARGV_FOR_SUBCOMMAND
                else argv[0]
            )
            raise GitError(
                f"{subcmd} failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        return result
