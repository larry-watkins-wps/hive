"""Sleep consolidation pipeline — spec §D.5.

:class:`SleepCoordinator` executes the 9-step pipeline that runs when a region
transitions BOOTSTRAP/WAKE → SLEEP. Exactly one result shape:

  - ``no_change``         — nothing on disk changed (no commit).
  - ``committed_in_place`` — one commit, keep running.
  - ``committed_restart``  — one commit, runtime should verify and restart.

Failure policy (Principle XIV — "chaos is a feature"):

  - Non-retryable LLM failure during review raises :class:`LlmError`; the
    working tree is reset to HEAD so no partial state escapes.
  - Handler compile/syntax gate failure (§D.5.4) reverts the tree and returns
    ``no_change``; no commit is attempted.
  - :meth:`abort` is the emergency escape for cortisol spikes during sleep
    (spec §A.8): reset the tree, log, never raise. Runtime observes the
    return and transitions phase back to WAKE.

Pre-restart verification (§D.5.5) is explicitly runtime's concern (Task 3.15)
— this module only returns ``restart=True`` and lets the runtime run its
final verification before publishing the restart request.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import structlog

from region_template.errors import LlmError
from region_template.llm_adapter import CompletionRequest, Message
from region_template.prompt_assembly import load_system_prompt
from region_template.self_modify import _HANDLER_REASON_MIN, HandlerWrite
from region_template.types import LifecyclePhase

if TYPE_CHECKING:
    from region_template.git_tools import CommitResult, GitTools
    from region_template.llm_adapter import LlmAdapter
    from region_template.memory import MemoryStore
    from region_template.self_modify import SelfModifyTools

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result types (spec §D.5.2)
# ---------------------------------------------------------------------------


SleepStatus = Literal[
    "no_change",
    "committed_in_place",
    "committed_restart",
]


SleepTrigger = Literal[
    "quiet_window",
    "explicit_request",
    "heartbeat_cycle",
    "external_command",
    "stm_pressure",
]


@dataclass(frozen=True)
class SleepResult:
    """Return shape of :meth:`SleepCoordinator.run` (spec D.5.2).

    ``sha`` is ``None`` when no commit was made; otherwise it is the full
    40-char SHA of the single commit this sleep produced.
    """

    status: SleepStatus
    restart: bool
    sha: str | None = None
    events_reviewed: int = 0
    ltm_writes: int = 0
    stm_pruned: int = 0


@dataclass(frozen=True)
class _ReviewOutput:
    """Parsed LLM review result — internal.

    ``appendix_entry`` replaces the removed ``prompt_edit`` field
    (see ``docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md``).
    The LLM emits only the new appendix section body; the framework
    prepends the timestamped H2 header via
    :class:`region_template.appendix.AppendixStore`.
    """

    ltm_candidates: list[dict[str, Any]] = field(default_factory=list)
    prune_keys: list[str] = field(default_factory=list)
    appendix_entry: str | None = None
    handler_edits: list[dict[str, Any]] = field(default_factory=list)
    needs_restart: bool = False
    reason: str = ""


# JSON schema shown to the LLM in the review prompt.
# Keeps the reply constrained and easy to parse. This constant is passed as
# a VALUE to ``template.format(review_schema=_REVIEW_SCHEMA_STR)`` — only the
# template itself is format-substituted, so the schema must use single
# braces. (An earlier version doubled them on the mistaken assumption that
# this string would also pass through ``str.format``; the LLM then saw
# ``{{...}}`` literally and the JSON was malformed.)
_REVIEW_SCHEMA_STR = """{
  "ltm_candidates": [
    {"filename": "str", "content": "str", "topic": "str",
      "importance": 0.0, "tags": ["str"], "reason": "str",
      "emotional_tag": "str or null"}
  ],
  "prune_keys": ["str"],
  "appendix_entry": "str or null",
  "handler_edits": [{"path": "str", "content": "str", "delete": false}],
  "needs_restart": false,
  "reason": "str"
}"""


# Strips ```json ... ``` fences from LLM output.
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)

# Debug-slice size for the review-decode failure log. Big enough to see the
# response opening + the tail that broke parsing.
_REVIEW_DEBUG_HEAD = 400
_REVIEW_DEBUG_TAIL = 200


def _clamp_reason(reason: str, max_len: int = 200) -> str:
    """Truncate an LLM-produced reason to fit the §A.7.1 cap.

    A narrative reason longer than ``max_len`` gets cut to ``max_len - 3``
    characters with a ``...`` suffix — preserves the gist while keeping the
    field validator happy. Short reasons pass through unchanged.
    """
    s = reason.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Runtime protocol
# ---------------------------------------------------------------------------


class _RuntimeLike(Protocol):
    """Narrow interface :class:`SleepCoordinator` needs from the runtime.

    ``Task 3.15`` (``region_template.runtime``) will wire a concrete
    ``RegionRuntime`` that fulfils this protocol.
    """

    region_name: str
    region_root: Path
    memory: MemoryStore
    llm: LlmAdapter
    tools: SelfModifyTools
    git: GitTools

    @property
    def phase(self) -> LifecyclePhase: ...


# ---------------------------------------------------------------------------
# SleepCoordinator
# ---------------------------------------------------------------------------


class SleepCoordinator:
    """Runs the 9-step sleep pipeline (spec D.5.1).

    One sleep produces **at most one** git commit. LLM failure during the
    review step raises :class:`LlmError`; the working tree is reset to HEAD
    so no partial state escapes (Principle XIV). :meth:`abort` is the
    emergency exit for cortisol spikes during sleep.
    """

    def __init__(self, runtime: _RuntimeLike) -> None:
        self._runtime = runtime
        self._log = log.bind(region=runtime.region_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self, trigger: SleepTrigger = "explicit_request"
    ) -> SleepResult:
        """Run the full 9-step sleep pipeline.

        Args:
            trigger: the classifier used in the commit message (D.5.6). One
                of :data:`SleepTrigger`.

        Returns:
            :class:`SleepResult` with status, restart flag and optional sha.

        Raises:
            :class:`LlmError`: non-retryable LLM failure during review.
                Working tree is reverted to HEAD before the exception
                escapes, so callers see a clean repo.
        """
        try:
            snap = await self._snapshot_stm()
            review = await self._review_events(snap)
            ltm_writes = await self._integrate_to_ltm(review)
            stm_pruned = await self._prune_stm(review.prune_keys)
            await self._rebuild_index()

            prompt_changed = False
            handlers_changed = False

            if review.appendix_entry:
                # Task 7 replaces this with ``self._append_appendix(...)``.
                # For Task 4 we reuse the old whole-file-rewrite path so the
                # field rename is a pure data-layer change (no behaviour
                # drift). The schema now asks the LLM for an appendix body
                # rather than a full rewrite, but no live region emits the
                # new shape yet — PFC was reverted in the prior session.
                await self._apply_prompt_edit(
                    review.appendix_entry, reason=review.reason
                )
                prompt_changed = True

            if review.handler_edits:
                ok = await self._apply_handler_edits(
                    review.handler_edits, reason=review.reason
                )
                if not ok:
                    # D.5.4 — gate failed. Revert and mark skipped.
                    self._log.warning("sleep_handler_gate_failed")
                    await self._revert_working_tree()
                    return SleepResult(
                        status="no_change",
                        restart=False,
                        sha=None,
                        events_reviewed=len(snap.get("recent_events", [])),
                        ltm_writes=0,
                        stm_pruned=0,
                    )
                handlers_changed = True

            events_reviewed = len(snap.get("recent_events", []))

            # If nothing substantive changed, return no_change. Revert the
            # working tree so spurious byproducts (e.g. index.json rewrite
            # with a new timestamp, pycache files from compileall) don't
            # leak across the sleep boundary — "no commit" means "no
            # change".
            anything_changed = (
                ltm_writes > 0
                or stm_pruned > 0
                or prompt_changed
                or handlers_changed
            )
            if not anything_changed:
                await self._revert_working_tree()
                return SleepResult(
                    status="no_change",
                    restart=False,
                    sha=None,
                    events_reviewed=events_reviewed,
                    ltm_writes=ltm_writes,
                    stm_pruned=stm_pruned,
                )

            # Build the commit message (D.5.6) and commit.
            commit_msg = self._format_commit_message(
                trigger=trigger,
                events_reviewed=events_reviewed,
                ltm_writes=ltm_writes,
                ltm_files=[
                    c.get("filename", "<unknown>")
                    for c in review.ltm_candidates
                ],
                stm_pruned=stm_pruned,
                prompt_changed=prompt_changed,
                handlers_changed=handlers_changed,
                restart=review.needs_restart
                and (handlers_changed or prompt_changed),
                reason=review.reason,
            )
            commit = await self._commit(commit_msg)
        except LlmError:
            # LLM failed during review (step 2) or parsing — before any
            # on-disk writes we control. Revert anyway in case something
            # partial got through (e.g. an index rebuild write), then
            # surface to the runtime.
            self._log.error("sleep_llm_error_during_review")
            await self._revert_working_tree()
            raise
        except BaseException:
            # Any other failure after LTM/STM writes or during prompt /
            # handler / commit steps — revert before bubbling up, to honour
            # the "no partial commits" guarantee (Principle XIV). Covers
            # e.g. oversized prompt_edit raising ConfigError, compileall
            # subprocess failure, GitError on commit, asyncio.CancelledError.
            await self._revert_working_tree()
            raise

        self._log.info(
            "sleep_committed",
            sha=commit.sha,
            ltm_writes=ltm_writes,
            stm_pruned=stm_pruned,
            prompt_changed=prompt_changed,
            handlers_changed=handlers_changed,
            needs_restart=review.needs_restart,
        )

        # Restart is only sensible when handlers or the prompt changed —
        # STM/LTM writes on their own don't require a process bounce.
        needs_restart = review.needs_restart and (
            handlers_changed or prompt_changed
        )
        if needs_restart:
            return SleepResult(
                status="committed_restart",
                restart=True,
                sha=commit.sha,
                events_reviewed=events_reviewed,
                ltm_writes=ltm_writes,
                stm_pruned=stm_pruned,
            )
        return SleepResult(
            status="committed_in_place",
            restart=False,
            sha=commit.sha,
            events_reviewed=events_reviewed,
            ltm_writes=ltm_writes,
            stm_pruned=stm_pruned,
        )

    async def abort(self, reason: str) -> None:
        """Emergency rollback from SLEEP (spec A.8).

        Called when cortisol spikes above ``sleep_abort_cortisol_threshold``
        during sleep (default 0.85) — biology analog to nightmare/wakeup.

        Reverts any staged-but-uncommitted changes and logs. Never raises —
        it's the emergency exit, already-in-exceptional-state. The runtime
        observes the return and transitions phase back to WAKE.
        """
        try:
            await self._revert_working_tree()
            self._log.warning("sleep_aborted", reason=reason)
        except Exception as exc:  # noqa: BLE001 — abort must not raise
            # We already-in-exceptional-state; swallow-and-log is the right
            # posture. A failing revert here means the runtime is probably
            # going to get crashed out by another mechanism anyway.
            self._log.error(
                "sleep_abort_revert_failed",
                reason=reason,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    async def _snapshot_stm(self) -> dict[str, Any]:
        """Step 1: read-only copy of STM (slots + recent_events ring).

        :class:`MemoryStore` doesn't expose a single ``snapshot_stm`` method,
        so we assemble the shape the review prompt wants from its public
        async API.
        """
        slots = await self._runtime.memory.list_stm()
        events = await self._runtime.memory.recent_events()
        # Slots come back as ``StmSlot`` dataclasses; flatten to a dict
        # of ``key → value`` for the prompt (tags/origin are noise here).
        return {
            "slots": {s.key: s.value for s in slots},
            "recent_events": events,
        }

    async def _review_events(self, snap: dict[str, Any]) -> _ReviewOutput:
        """Step 2: LLM review of recent events. Returns parsed proposals.

        The system message is assembled by ``load_system_prompt``:
        starter ``prompt.md`` + optional rolling appendix. The user
        message is rendered from ``sleep_prompts/default_review_user.md``
        with the STM snapshot + recent events + schema. Keeping the
        large, stable half in ``role="system"`` enables prompt caching
        (``cache_strategy="system"`` is the default).
        """
        system_text = load_system_prompt(self._runtime.region_root)
        user_text = self._render_review_user_prompt(snap)
        req = CompletionRequest(
            messages=[
                Message(role="system", content=system_text),
                Message(role="user", content=user_text),
            ],
            purpose="sleep_review",
        )
        result = await self._runtime.llm.complete(req)
        return self._parse_review_output(result.text)

    async def _integrate_to_ltm(self, review: _ReviewOutput) -> int:
        """Step 3: write candidate episodes/knowledge to LTM.

        Returns the number of successful writes. Individual writes that
        fail validation inside ``tools.write_ltm`` are caught and skipped
        with a WARN — we don't abort the whole sleep over one bad filename.
        """
        count = 0
        for candidate in review.ltm_candidates:
            filename = candidate.get("filename")
            content = candidate.get("content", "")
            if not isinstance(filename, str) or not filename:
                self._log.warning(
                    "ltm_candidate_skipped", reason="missing_filename"
                )
                continue
            try:
                await self._runtime.tools.write_ltm(
                    filename=filename,
                    content=content,
                    reason=candidate.get("reason", "sleep_consolidation"),
                    topic=candidate.get("topic", "episode"),
                    importance=float(candidate.get("importance", 0.5)),
                    tags=list(candidate.get("tags", []) or []),
                    emotional_tag=candidate.get("emotional_tag"),
                )
            except Exception as exc:  # noqa: BLE001
                # Trust write_ltm to raise on invalid filenames etc.; skip
                # the candidate rather than aborting the full sleep.
                self._log.warning(
                    "ltm_candidate_write_failed",
                    filename=filename,
                    error=str(exc),
                )
                continue
            count += 1
        return count

    async def _prune_stm(self, prune_keys: list[str]) -> int:
        """Step 4: delete specific STM slots the review identified.

        Non-existent keys are silently skipped (idempotent).
        """
        count = 0
        for key in prune_keys:
            try:
                removed = await self._runtime.memory.delete_stm(key)
            except Exception as exc:  # noqa: BLE001
                self._log.warning(
                    "stm_prune_failed", key=key, error=str(exc)
                )
                continue
            if removed:
                count += 1
        return count

    async def _rebuild_index(self) -> None:
        """Step 5: one-shot scan of ``ltm/`` -> ``index.json``.

        Delegates to :meth:`MemoryStore.build_index`.
        """
        await self._runtime.memory.build_index()

    async def _apply_prompt_edit(self, new_text: str, reason: str) -> None:
        """Step 6: persist a revised prompt via SelfModifyTools.

        Spec §A.7.1 requires ``reason`` to be 1..200 chars — any
        non-whitespace string is valid, so a simple ``bool`` fallback
        is sufficient here. Long narrative reasons from the LLM are
        truncated to the 200-char cap with an ellipsis so they don't
        fail the whole sleep cycle.
        """
        effective_reason = (
            _clamp_reason(reason) if reason and reason.strip() else "sleep_revision"
        )
        await self._runtime.tools.edit_prompt(
            new_text=new_text, reason=effective_reason
        )

    async def _apply_handler_edits(
        self, edits: list[dict[str, Any]], reason: str
    ) -> bool:
        """Step 7: apply handler writes/deletes with compile gate (D.5.4).

        ``SelfModifyTools.edit_handlers`` already runs ``ast.parse`` on every
        resulting ``.py`` file (syntax gate). We additionally run
        ``python -m compileall`` on the handlers dir as the bytecode gate.

        Returns:
            ``True`` on success; ``False`` if either gate failed.
        """
        writes, deletes = self._split_handler_edits(edits)
        # Spec §A.7.3: handler reasons must be >= _HANDLER_REASON_MIN chars
        # AND <= 200 chars (§A.7.1). A truthy-only fallback would pass a
        # short LLM reason like "ok" straight through and fail validation.
        # A long narrative reason similarly fails. Length-clamp on both ends.
        effective_reason = (
            _clamp_reason(reason)
            if reason and len(reason.strip()) >= _HANDLER_REASON_MIN
            else "sleep_handler_revision"
        )

        try:
            result = await self._runtime.tools.edit_handlers(
                writes=writes, deletes=deletes, reason=effective_reason
            )
        except Exception as exc:  # noqa: BLE001
            # e.g. sandbox escape on a malformed path. Treat as gate failure.
            self._log.warning(
                "edit_handlers_raised", error=str(exc)
            )
            return False

        if not result.ok:
            self._log.warning(
                "edit_handlers_syntax_gate_failed", error=result.error
            )
            return False

        # Bytecode gate — compileall. Runs *after* writes land on disk.
        # Pass ``PYTHONDONTWRITEBYTECODE=1`` so ordinary imports the
        # subprocess triggers don't leave stray ``.pyc`` behind, and ALSO
        # remove ``handlers/__pycache__/`` after the run — ``compileall``
        # itself ignores the env var because its explicit purpose is to
        # compile, so we need the belt-and-braces cleanup to keep the
        # region's git repo free of bytecode noise. The repo's
        # ``.gitignore`` (written by ``GitTools._ensure_repo``) is the
        # third line of defence.
        handlers_dir = self._runtime.region_root / "handlers"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "compileall",
                "-q",
                str(handlers_dir),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await proc.communicate()
            compileall_ok = proc.returncode == 0
            if not compileall_ok:
                self._log.warning(
                    "compileall_gate_failed",
                    stderr=stderr.decode(errors="replace").strip(),
                )
        except FileNotFoundError as exc:
            # Python binary missing from PATH — can't gate. Don't block
            # sleep: ast.parse already ran inside edit_handlers.
            self._log.warning(
                "compileall_unavailable", error=str(exc)
            )
            compileall_ok = True
        finally:
            # Always clean up any pycache the subprocess wrote; do this in
            # a finally so gate failures don't leave bytecode on disk either.
            pycache_dir = handlers_dir / "__pycache__"
            if pycache_dir.exists():
                await asyncio.to_thread(
                    shutil.rmtree, pycache_dir, ignore_errors=True
                )
        return compileall_ok

    async def _commit(self, message: str) -> CommitResult:
        """Step 8: ``SelfModifyTools.commit_changes``."""
        return await self._runtime.tools.commit_changes(message)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render_review_user_prompt(self, snap: dict[str, Any]) -> str:
        """Render the user-side review prompt (STM + events + schema).

        The system-side (starter prompt + rolling appendix) is assembled
        by :func:`region_template.prompt_assembly.load_system_prompt` and
        attached to the :class:`CompletionRequest` as a separate
        ``Message(role="system", ...)``.
        """
        template_path = (
            Path(__file__).parent / "sleep_prompts" / "default_review_user.md"
        )
        template = template_path.read_text(encoding="utf-8")
        # Trim snapshot fields to ~2 KB each so the prompt doesn't blow up.
        stm_summary = json.dumps(
            snap.get("slots", {}), ensure_ascii=False
        )[:2000]
        recent = json.dumps(
            snap.get("recent_events", []), ensure_ascii=False
        )[:2000]
        return template.format(
            stm_summary=stm_summary,
            recent_events=recent,
            modulator_snapshot="{}",
            self_state="{}",
            review_schema=_REVIEW_SCHEMA_STR,
        )

    def _parse_review_output(self, text: str) -> _ReviewOutput:
        """Parse the LLM's JSON reply. Tolerates ```json fenced blocks.

        Raises :class:`LlmError` with kind ``review_json_decode_error`` on
        malformed output — the runtime treats this as a non-retryable LLM
        failure.
        """
        match = _CODE_FENCE_RE.search(text)
        payload = match.group(1) if match else text.strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            # Surface enough context to diagnose common failure modes
            # (unescaped newlines, stray trailing commas, LLM preamble text
            # outside the ```json fence). structlog caps long fields; the
            # head/tail slices here are the minimum useful cross-section.
            self._log.warning(
                "review_json_decode_debug",
                text_len=len(text),
                text_head=text[:_REVIEW_DEBUG_HEAD],
                text_tail=(
                    text[-_REVIEW_DEBUG_TAIL:]
                    if len(text) > _REVIEW_DEBUG_HEAD
                    else ""
                ),
                has_fence=match is not None,
                parse_error=str(exc),
            )
            raise LlmError(
                "review_json_decode_error", retryable=False
            ) from exc
        if not isinstance(data, dict):
            raise LlmError("review_json_decode_error", retryable=False)

        appendix_raw = data.get("appendix_entry")
        appendix_entry: str | None
        if isinstance(appendix_raw, str) and appendix_raw.strip():
            appendix_entry = appendix_raw
        else:
            appendix_entry = None

        # ``data.get("prompt_edit")`` is intentionally ignored — the field
        # was renamed to ``appendix_entry`` and a legacy LLM response may
        # still emit the old shape during the Task 4 → Task 7 rollout.
        # Silent-ignore (no warning log) keeps the transition quiet.
        return _ReviewOutput(
            ltm_candidates=list(data.get("ltm_candidates") or []),
            prune_keys=list(data.get("prune_keys") or []),
            appendix_entry=appendix_entry,
            handler_edits=list(data.get("handler_edits") or []),
            needs_restart=bool(data.get("needs_restart", False)),
            reason=str(data.get("reason", "") or ""),
        )

    def _split_handler_edits(
        self, edits: list[dict[str, Any]]
    ) -> tuple[list[HandlerWrite], list[str]]:
        """Split the review's handler_edits list into writes vs deletes."""
        writes: list[HandlerWrite] = []
        deletes: list[str] = []
        for edit in edits:
            path = edit.get("path")
            if not isinstance(path, str) or not path:
                continue
            if bool(edit.get("delete", False)):
                deletes.append(path)
                continue
            content = edit.get("content", "")
            writes.append(HandlerWrite(path=path, content=str(content)))
        return writes, deletes

    def _format_commit_message(
        self,
        *,
        trigger: SleepTrigger,
        events_reviewed: int,
        ltm_writes: int,
        ltm_files: list[str],
        stm_pruned: int,
        prompt_changed: bool,
        handlers_changed: bool,
        restart: bool,
        reason: str,
    ) -> str:
        """Format the per-commit message body per spec D.5.6."""
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        return (
            f"sleep: {trigger} @ {ts}\n"
            "\n"
            f"- events reviewed: {events_reviewed}\n"
            f"- ltm writes: {ltm_writes}  files: {ltm_files}\n"
            f"- stm pruned: {stm_pruned} slots\n"
            f"- prompt: {'changed' if prompt_changed else 'unchanged'}\n"
            f"- handlers: {'changed' if handlers_changed else 'unchanged'}\n"
            f"- restart required: {'yes' if restart else 'no'}\n"
            "\n"
            f"reason: {reason}\n"
        )

    async def _revert_working_tree(self) -> None:
        """Drop any staged/unstaged/untracked edits back to the last commit.

        Delegates to :meth:`GitTools.reset_working_tree`, which runs both
        ``git reset --hard HEAD`` and ``git clean -fd`` — the latter is
        necessary because mid-sleep handler writes land as untracked files
        until :meth:`SelfModifyTools.commit_changes` stages them. Runs on
        a worker thread so the event loop isn't blocked.
        """
        await asyncio.to_thread(self._runtime.git.reset_working_tree)
