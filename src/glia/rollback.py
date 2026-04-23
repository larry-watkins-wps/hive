"""glia/rollback.py — single-shot region rollback + relaunch (spec §E.5).

This module provides a **stateless mechanism** for rolling a region back to its
previous commit and relaunching its container:

    1.  ``git rev-parse HEAD~1`` inside ``regions/<name>/`` — find the parent
        sha.  No parent → :class:`RollbackResult` ``ok=False``.
    2.  ``git revert --no-edit HEAD`` — record the revert as a *new* commit
        (never rewinds history, so sleep's published-sha lineage stays intact).
    3.  :meth:`Launcher.stop_region` + :meth:`Launcher.launch_region` via
        :func:`asyncio.to_thread`.
    4.  Publish ``hive/metacognition/error/detected`` with
        ``kind="region_rollback"``.

Retry policy lives at **supervisor** scope (Task 5.9), not here.  The plan text
mentions "rollback again (up to N=3)" — that's the supervisor's state machine,
which calls :meth:`Rollback.rollback_region` repeatedly and
:meth:`Rollback.mark_region_dead` once exhausted.  This module does ONE
rollback attempt and returns the outcome.

Spec §E.5 final paragraph says "if rollback fails, glia stops and publishes
metacog rollback_failed".  :meth:`mark_region_dead` implements the publish;
"stops" is again supervisor-scope.

Design notes
------------
* **Injectable subprocess runner** — tests pass a ``MagicMock``; production
  uses :func:`subprocess.run`.  No real docker or git required in unit tests.
* **Publish signature** — takes ``Callable[[Envelope], Awaitable[None]]`` to
  match the ``MqttClient.publish`` shape used elsewhere (spec §B.2).
* **Publish errors on success path are swallowed** — revert + relaunch already
  completed successfully; a broker hiccup must not flip ``ok`` to False.  We
  log and return ``ok=True``.  On the *failure* path (relaunch crashed)
  publish errors are also swallowed: we still return the primary failure.
* **Launcher calls wrapped in ``asyncio.to_thread``** — launcher is sync.
"""
from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from glia.launcher import GliaError, Launcher
from shared.message_envelope import Envelope
from shared.topics import METACOGNITION_ERROR_DETECTED

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RollbackResult:
    """Outcome of a single :meth:`Rollback.rollback_region` attempt."""

    ok: bool
    reverted_to: str | None = None
    reason: str | None = None


# Type alias for the injected subprocess runner.  Mirrors ``subprocess.run``'s
# kwargs subset we actually use.
_Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class Rollback:
    """One-shot per-region git revert + relaunch mechanism.

    Instances are stateless across regions and across calls — the supervisor
    owns any retry counters.

    Parameters
    ----------
    launcher:
        Sync :class:`Launcher` used to stop and restart the container.
    publish:
        Awaitable publish function; typically ``MqttClient.publish``.
    regions_root:
        Directory containing per-region git checkouts.  Default ``regions``
        (relative to the glia container's cwd).  Tests inject ``tmp_path``.
    runner:
        Subprocess runner.  Defaults to :func:`subprocess.run`.
    """

    def __init__(
        self,
        launcher: Launcher,
        *,
        publish: Callable[[Envelope], Awaitable[None]],
        regions_root: Path = Path("regions"),
        runner: _Runner = subprocess.run,
    ) -> None:
        self._launcher = launcher
        self._publish = publish
        self._regions_root = regions_root
        self._runner = runner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def rollback_region(self, region: str, reason: str) -> RollbackResult:
        """Revert ``regions/<region>/`` to HEAD~1 and relaunch.

        Returns a :class:`RollbackResult`.  Never raises (subprocess + launcher
        errors are all funnelled into ``ok=False`` results; publish errors are
        logged and swallowed).

        The caller (supervisor) inspects ``ok`` and decides whether to retry.
        """
        root = self._regions_root / region

        # 1. .git check
        if not (root / ".git").exists():
            log.warning(
                "rollback.no_git",
                region=region,
                reason=reason,
                root=str(root),
            )
            return RollbackResult(ok=False, reason="no git")

        # 2. find parent sha
        rev_parse = self._runner(
            ["git", "rev-parse", "HEAD~1"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        prev = rev_parse.stdout.strip() if rev_parse.stdout else ""
        if rev_parse.returncode != 0 or not prev:
            log.warning(
                "rollback.no_parent",
                region=region,
                reason=reason,
                returncode=rev_parse.returncode,
                stderr=rev_parse.stderr,
            )
            return RollbackResult(ok=False, reason="no parent commit")

        # 3. git revert --no-edit HEAD
        revert = self._runner(
            ["git", "revert", "--no-edit", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if revert.returncode != 0:
            stderr = (revert.stderr or "").strip()
            log.error(
                "rollback.revert_failed",
                region=region,
                reason=reason,
                stderr=stderr,
            )
            return RollbackResult(
                ok=False,
                reason=f"git revert failed: {stderr}",
            )

        # 4. relaunch (stop + launch) — wrap sync launcher in asyncio.to_thread
        try:
            await asyncio.to_thread(self._launcher.stop_region, region)
            await asyncio.to_thread(self._launcher.launch_region, region)
        except GliaError as exc:
            log.error(
                "rollback.relaunch_failed",
                region=region,
                reason=reason,
                error=str(exc),
            )
            await self._publish_quiet(
                _build_envelope(
                    kind="rollback_failed",
                    detail=f"relaunch failed after revert: {exc}",
                    context={
                        "region": region,
                        "reason": reason,
                        "reverted_sha": prev,
                    },
                )
            )
            return RollbackResult(
                ok=False,
                reason=f"relaunch failed: {exc}",
            )

        # 5. announce success
        log.info(
            "rollback.ok",
            region=region,
            reason=reason,
            reverted_to=prev,
        )
        await self._publish_quiet(
            _build_envelope(
                kind="region_rollback",
                detail=f"rolled back to {prev}",
                context={
                    "region": region,
                    "reason": reason,
                    "reverted_sha": prev,
                },
            )
        )
        return RollbackResult(ok=True, reverted_to=prev)

    async def mark_region_dead(self, region: str, reason: str) -> None:
        """Publish a metacog ``rollback_failed`` event.

        Called by the supervisor after the retry budget is exhausted.  Does
        not manage container state — the region is presumed already stopped.
        """
        log.error("rollback.region_dead", region=region, reason=reason)
        await self._publish_quiet(
            _build_envelope(
                kind="rollback_failed",
                detail=f"region {region} marked dead: {reason}",
                context={"region": region, "reason": reason},
            )
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _publish_quiet(self, envelope: Envelope) -> None:
        """Publish; log + swallow any exception.

        The mechanism has already made its side-effect (revert or mark-dead);
        a broker hiccup must not undo that outcome.
        """
        try:
            await self._publish(envelope)
        except Exception as exc:  # noqa: BLE001 — deliberately broad
            log.warning(
                "rollback.publish_failed",
                topic=envelope.topic,
                error=str(exc),
            )


def _build_envelope(
    *, kind: str, detail: str, context: dict[str, Any]
) -> Envelope:
    """Construct the metacog-error envelope payload per spec §E.5."""
    return Envelope.new(
        source_region="glia",
        topic=METACOGNITION_ERROR_DETECTED,
        content_type="application/json",
        data={"kind": kind, "detail": detail, "context": context},
    )
