"""Self-modification tools — spec §A.7.

:class:`SelfModifyTools` is the fixed API a region uses to edit its own
DNA during SLEEP. Every destructive tool is:

  * sandboxed to ``regions/<name>/`` (any escape raises
    :class:`~region_template.errors.SandboxEscape`),
  * gated on a capability from the region's
    :class:`~region_template.types.CapabilityProfile`
    (missing → :class:`~region_template.errors.CapabilityDenied`), and
  * gated on ``LifecyclePhase.SLEEP`` via the
    :func:`~region_template.capability.sleep_only` decorator
    (wrong phase → :class:`~region_template.errors.PhaseViolation`).

The one exception is :meth:`SelfModifyTools.write_stm` — it is callable
in WAKE too, because STM is the region's working state.

Spec-vs-plan deviation: the plan lists ``write_memory`` as one tool, but
spec §A.7.4 splits it into two methods — :meth:`write_stm` (WAKE-callable,
no git commit) and :meth:`write_ltm` (sleep-only, committed). We follow
the spec.

Runtime seam
------------
:class:`_RuntimeLike` is the narrow protocol this module needs from the
runtime. Task 3.15 will wire a concrete ``RegionRuntime`` that fulfils
it. In particular, :meth:`_RuntimeLike.publish_spawn_request` publishes
on ``hive/system/spawn/request`` and returns an :class:`asyncio.Future`
that resolves when a ``spawn/complete`` or ``spawn/failed`` message
arrives with the matching ``correlation_id`` on the SLEEP-phase
listener (spec §A.7.7).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import dataclasses
import io
import os
import re
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol

import structlog
from ruamel.yaml import YAML

from region_template.capability import requires_capability, sleep_only
from region_template.errors import (
    ConfigError,
    SandboxEscape,
)
from region_template.git_tools import CommitResult, GitTools
from region_template.memory import LtmMetadata, MemoryStore
from region_template.types import CapabilityProfile, LifecyclePhase

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Reason-length bounds (spec §A.7.1 / §A.7.2).
_REASON_MIN = 1
_REASON_MAX = 200
# Handlers are high-impact — tighter minimum (§A.7.3).
_HANDLER_REASON_MIN = 10

# edit_prompt: UTF-8 budget (§A.7.1).
_PROMPT_MAX_BYTES = 64 * 1024

# Spawn block timeout (§A.7.7). Module-level to let tests compress it.
_SPAWN_TIMEOUT_S: float = 30.0

# Region name validation regex (§A.7.7 SpawnProposal.name, §F.2).
_REGION_NAME_RE = re.compile(r"[a-z][a-z0-9_]{2,30}")

# Git sha length (full). Used by CommitResult shape assertions in tests.
_SHA_LEN = 40


# ---------------------------------------------------------------------------
# Result + request dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditResult:
    """Return shape for every file-editing tool (spec §A.7.1 etc.).

    ``ok=False`` signals an expected failure (e.g. syntax error in
    :meth:`SelfModifyTools.edit_handlers`); the ``error`` field carries
    a human-readable message.
    """

    ok: bool
    path: Path | None = None
    bytes_written: int = 0
    diff_lines: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SubscriptionEntry:
    """One row in ``subscriptions.yaml`` (spec §A.7.2)."""

    topic: str
    qos: int = 1
    description: str = ""


@dataclass(frozen=True)
class HandlerWrite:
    """One write request for :meth:`SelfModifyTools.edit_handlers`."""

    path: str  # relative to handlers/, e.g. "on_audio.py"
    content: str


@dataclass(frozen=True)
class SpawnProposal:
    """Payload for :meth:`SelfModifyTools.spawn_new_region` (spec §A.7.7)."""

    name: str
    role: str
    modality: str | None
    llm: dict[str, Any]
    capabilities: CapabilityProfile
    starter_prompt: str
    initial_subscriptions: list[SubscriptionEntry]


@dataclass(frozen=True)
class SpawnResult:
    """Result of :meth:`SelfModifyTools.spawn_new_region`."""

    ok: bool
    sha: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Runtime protocol
# ---------------------------------------------------------------------------


class _RuntimeLike(Protocol):
    """Narrow interface :class:`SelfModifyTools` needs from the runtime.

    Kept as a ``Protocol`` so tests can stub it without a full
    ``RegionRuntime``.
    """

    @property
    def phase(self) -> LifecyclePhase: ...

    async def publish_restart_request(self, reason: str) -> None: ...

    async def publish_spawn_request(
        self,
        proposal: SpawnProposal,
        correlation_id: str,
    ) -> Awaitable[SpawnResult]: ...

    async def shutdown(self, reason: str) -> None: ...


# ---------------------------------------------------------------------------
# SelfModifyTools
# ---------------------------------------------------------------------------


class SelfModifyTools:
    """Sleep-only, capability-gated self-modification API (spec §A.7).

    Stored attributes satisfy the decorators in
    :mod:`region_template.capability`:

      * ``self._caps`` — a ``dict[str, bool]`` mirror of the region's
        :class:`CapabilityProfile`, consulted by
        :func:`~region_template.capability.requires_capability`.
      * ``self._runtime`` — an object with a ``.phase`` attribute of
        type :class:`~region_template.types.LifecyclePhase`, consulted
        by :func:`~region_template.capability.sleep_only`.
    """

    def __init__(
        self,
        *,
        region_name: str,
        region_root: Path,
        capabilities: CapabilityProfile | dict[str, bool],
        runtime: _RuntimeLike,
        git_tools: GitTools,
        memory: MemoryStore,
        bootstrap_sha: str,
    ) -> None:
        self._name = region_name
        self._root = Path(region_root).resolve()
        # Normalize to a dict so the decorators' ``self._caps.get(c)``
        # call works regardless of whether callers hand us a dict or a
        # Pydantic CapabilityProfile.
        self._caps: dict[str, bool] = _as_caps_dict(capabilities)
        self._runtime = runtime
        self._git = git_tools
        self._memory = memory
        self._bootstrap_sha = bootstrap_sha
        self._log = log.bind(region=region_name)

    # ------------------------------------------------------------------
    # edit_prompt (§A.7.1)
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def edit_prompt(self, new_text: str, reason: str) -> EditResult:
        """Overwrite ``regions/<name>/prompt.md`` atomically."""
        _validate_reason(reason, min_len=_REASON_MIN, max_len=_REASON_MAX)
        _validate_utf8_size(new_text, max_bytes=_PROMPT_MAX_BYTES)
        target = self._sandboxed_path("prompt.md")
        bytes_written, diff = _atomic_write_text(target, new_text)
        self._log.info(
            "edit_prompt",
            path=str(target),
            bytes_written=bytes_written,
            diff_lines=diff,
            reason=reason,
        )
        return EditResult(
            ok=True,
            path=target,
            bytes_written=bytes_written,
            diff_lines=diff,
        )

    # ------------------------------------------------------------------
    # edit_subscriptions (§A.7.2)
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def edit_subscriptions(
        self,
        subscriptions: list[SubscriptionEntry],
        reason: str,
    ) -> EditResult:
        """Overwrite ``regions/<name>/subscriptions.yaml`` atomically."""
        _validate_reason(reason, min_len=_REASON_MIN, max_len=_REASON_MAX)
        for entry in subscriptions:
            _validate_topic(entry.topic)

        target = self._sandboxed_path("subscriptions.yaml")
        rows = [dataclasses.asdict(e) for e in subscriptions]
        yaml_text = _dump_yaml(rows)
        bytes_written, diff = _atomic_write_text(target, yaml_text)
        self._log.info(
            "edit_subscriptions",
            path=str(target),
            count=len(rows),
            bytes_written=bytes_written,
            reason=reason,
        )
        return EditResult(
            ok=True,
            path=target,
            bytes_written=bytes_written,
            diff_lines=diff,
        )

    # ------------------------------------------------------------------
    # edit_handlers (§A.7.3)
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def edit_handlers(
        self,
        writes: list[HandlerWrite],
        deletes: list[str],
        reason: str,
    ) -> EditResult:
        """Create / overwrite / delete files under
        ``regions/<name>/handlers/``.

        After staging all requested changes, every resulting ``.py``
        file is parsed with :func:`ast.parse`. Any syntax error aborts
        the entire change set — nothing on disk is modified — and the
        result carries ``ok=False`` with a short error message.
        """
        _validate_reason(
            reason, min_len=_HANDLER_REASON_MIN, max_len=_REASON_MAX
        )
        for w in writes:
            _validate_handler_path(w.path)
        for d in deletes:
            _validate_handler_path(d)

        handlers_dir = self._sandboxed_path("handlers")
        # Confirm each resolved target stays inside handlers/.
        write_targets: list[tuple[Path, str]] = []
        for w in writes:
            target = self._sandboxed_path(Path("handlers") / w.path)
            # Belt-and-suspenders: also ensure it's under handlers/.
            try:
                target.relative_to(handlers_dir)
            except ValueError as exc:
                raise SandboxEscape(
                    f"handler path escapes handlers dir: {w.path!r}"
                ) from exc
            write_targets.append((target, w.content))

        delete_targets: list[Path] = []
        for d in deletes:
            target = self._sandboxed_path(Path("handlers") / d)
            try:
                target.relative_to(handlers_dir)
            except ValueError as exc:
                raise SandboxEscape(
                    f"handler path escapes handlers dir: {d!r}"
                ) from exc
            delete_targets.append(target)

        # Syntax-check every .py file in the *resulting* handlers/ tree.
        # For writes: parse the new content. For untouched files:
        # parse current disk contents. Files in delete_targets are
        # excluded from the check (they're about to be removed).
        deleted_paths = set(delete_targets)

        syntax_err = _syntax_check(
            handlers_dir=handlers_dir,
            proposed_writes=write_targets,
            deleted_paths=deleted_paths,
        )
        if syntax_err is not None:
            self._log.warning(
                "edit_handlers_syntax_error",
                error=syntax_err,
                reason=reason,
            )
            return EditResult(ok=False, error=syntax_err)

        # Apply — create dir, write files, then delete. Each write is
        # atomic via _atomic_write_text; deletes are best-effort (spec
        # is silent on missing-file semantics, so we tolerate them).
        handlers_dir.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        total_diff = 0
        for target, content in write_targets:
            bytes_written, diff = _atomic_write_text(target, content)
            total_bytes += bytes_written
            total_diff += diff
        for target in delete_targets:
            with contextlib.suppress(FileNotFoundError):
                target.unlink()

        self._log.info(
            "edit_handlers",
            writes=len(write_targets),
            deletes=len(delete_targets),
            reason=reason,
        )
        return EditResult(
            ok=True,
            path=handlers_dir,
            bytes_written=total_bytes,
            diff_lines=total_diff,
        )

    # ------------------------------------------------------------------
    # write_stm (§A.7.4) — WAKE-callable, no commit
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    async def write_stm(self, key: str, value: Any) -> None:
        """Upsert a key in ``memory/stm.json``.

        No ``@sleep_only`` — STM is the working-state of a live region
        and must be callable in WAKE (spec §A.7.4).
        """
        await self._memory.write_stm(key, value)

    # ------------------------------------------------------------------
    # write_ltm (§A.7.4) — sleep-only
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def write_ltm(
        self,
        filename: str,
        content: str,
        reason: str,
    ) -> EditResult:
        """Create or append to ``memory/ltm/<filename>.md``."""
        _validate_reason(reason, min_len=_REASON_MIN, max_len=_REASON_MAX)
        _validate_ltm_filename(filename)
        # Sandbox: full resolved path must stay under region_root.
        # (MemoryStore also validates relative-path safety.)
        _ = self._sandboxed_path(Path("memory") / "ltm" / filename)

        metadata = LtmMetadata(
            topic="self_modify",
            tags=[],
            importance=0.5,
            emotional_tag=None,
        )
        result = await self._memory.write_ltm(
            filename, content, metadata, reason
        )
        # Surface path as an absolute Path object for callers.
        path = (self._memory.root / "ltm" / result.path).resolve()
        self._log.info(
            "write_ltm",
            path=str(path),
            created=result.created,
            reason=reason,
        )
        return EditResult(
            ok=True,
            path=path,
            bytes_written=path.stat().st_size if path.exists() else 0,
            diff_lines=0,
        )

    # ------------------------------------------------------------------
    # commit_changes (§A.7.5)
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def commit_changes(self, message: str) -> CommitResult:
        """Stage + commit everything under the region root.

        Delegates to :meth:`GitTools.commit_all`. Runs the subprocess
        on a worker thread so the event loop isn't blocked.
        """
        return await asyncio.to_thread(self._git.commit_all, message)

    # ------------------------------------------------------------------
    # request_restart (§A.7.6)
    # ------------------------------------------------------------------
    @requires_capability("self_modify")
    @sleep_only
    async def request_restart(self, reason: str) -> dict[str, Any]:
        """Publish a restart request and shut down.

        Preconditions (framework-checked, per spec §A.7.6):

          1. Phase == SLEEP (decorator).
          2. ``git status --porcelain`` empty — caller must have
             already committed.
          3. HEAD sha has advanced past the bootstrap sha — at least
             one change since boot.

        Returns ``{"ok": False, "reason": ...}`` on precondition
        failure; ``{"ok": True}`` on success (after which the region
        has been asked to shut down).
        """
        _validate_reason(reason, min_len=_REASON_MIN, max_len=_REASON_MAX)
        if not self._git.status_clean():
            return {"ok": False, "reason": "uncommitted_changes"}
        current = await asyncio.to_thread(self._git.current_head_sha)
        if current == self._bootstrap_sha:
            return {"ok": False, "reason": "no_change_since_boot"}
        await self._runtime.publish_restart_request(reason)
        await self._runtime.shutdown("restart")
        return {"ok": True}

    # ------------------------------------------------------------------
    # spawn_new_region (§A.7.7) — privileged
    # ------------------------------------------------------------------
    @requires_capability("can_spawn")
    @sleep_only
    async def spawn_new_region(self, proposal: SpawnProposal) -> SpawnResult:
        """Publish a spawn request and await glia's reply (up to 30 s).

        Gated by ``can_spawn`` (granted only to ``anterior_cingulate``
        per §F.3). The runtime is responsible for correlating the
        published request with the reply arriving on the SLEEP-phase
        listener; this method only supplies the correlation id and
        awaits the runtime-provided future.
        """
        _validate_spawn_proposal(proposal)
        correlation_id = uuid.uuid4().hex

        future = await self._runtime.publish_spawn_request(
            proposal, correlation_id
        )
        try:
            result = await asyncio.wait_for(future, timeout=_SPAWN_TIMEOUT_S)
        except TimeoutError:
            # Best-effort cancel so the runtime can clean up its map.
            if hasattr(future, "cancel"):
                future.cancel()
            return SpawnResult(ok=False, reason="timeout")
        if not isinstance(result, SpawnResult):
            # Defensive: runtime stubs that return dicts etc.
            return SpawnResult(ok=False, reason="bad_reply")
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _sandboxed_path(self, relative: str | Path) -> Path:
        """Resolve *relative* under ``self._root``.

        Raises :class:`SandboxEscape` if the resolved path is outside
        the region root (spec §A.7.1). Uses
        :meth:`pathlib.PurePath.relative_to` for a strict prefix check.
        """
        candidate = Path(relative)
        # Refuse obviously hostile inputs before filesystem resolution.
        # (absolute paths + any ``..`` part — we don't want to rely on
        # ``resolve()`` alone, because it silently normalises away
        # traversal on non-existent intermediate dirs.)
        if candidate.is_absolute() or any(
            p == ".." for p in candidate.parts
        ):
            raise SandboxEscape(
                f"path escapes region root: {relative!r}"
            )
        target = (self._root / candidate).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise SandboxEscape(
                f"path escapes region root: {relative!r} -> {target}"
            ) from exc
        return target


# ---------------------------------------------------------------------------
# Module-level validation + IO helpers
# ---------------------------------------------------------------------------


def _as_caps_dict(caps: CapabilityProfile | dict[str, bool]) -> dict[str, bool]:
    """Coerce :class:`CapabilityProfile` → plain ``dict[str, bool]``.

    :func:`~region_template.capability.requires_capability` expects
    ``self._caps`` to be a dict with ``.get()``. Pydantic's
    ``model_dump()`` gives us that; plain dicts pass through.
    """
    if isinstance(caps, dict):
        return dict(caps)
    # Pydantic model — dump only the boolean fields; drop ``modalities``
    # (a list) and ``tool_use`` (a literal string) which aren't used as
    # capability flags.
    dumped = caps.model_dump()
    return {k: bool(v) for k, v in dumped.items() if isinstance(v, bool)}


def _validate_reason(reason: str, *, min_len: int, max_len: int) -> None:
    if not isinstance(reason, str):
        raise ConfigError(f"reason must be a string, got {type(reason).__name__}")
    length = len(reason)
    if length < min_len:
        raise ConfigError(
            f"reason too short: {length} chars (min {min_len})"
        )
    if length > max_len:
        raise ConfigError(
            f"reason too long: {length} chars (max {max_len})"
        )


def _validate_utf8_size(text: str, *, max_bytes: int) -> None:
    """Ensure *text* encodes to valid UTF-8 within the byte budget."""
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConfigError(f"text is not valid UTF-8: {exc}") from exc
    if len(encoded) > max_bytes:
        raise ConfigError(
            f"text too large: {len(encoded)} bytes (max {max_bytes})"
        )


def _validate_topic(topic: str) -> None:
    """Validate an MQTT subscription topic per spec §A.7.2.

    Rules:
      * non-empty string
      * no whitespace characters
      * no trailing slash
      * ``+`` wildcards only in the last or last-but-one segment
      * ``#`` wildcard only as the last segment
    """
    if not isinstance(topic, str) or not topic:
        raise ConfigError(f"topic must be a non-empty string: {topic!r}")
    if any(ch.isspace() for ch in topic):
        raise ConfigError(f"topic contains whitespace: {topic!r}")
    if topic.endswith("/"):
        raise ConfigError(f"topic has trailing slash: {topic!r}")
    segments = topic.split("/")
    last_idx = len(segments) - 1
    for i, seg in enumerate(segments):
        if seg == "#":
            if i != last_idx:
                raise ConfigError(
                    f"# wildcard must be last segment: {topic!r}"
                )
        elif "#" in seg:
            # '#' only valid as an entire segment.
            raise ConfigError(f"bad '#' placement: {topic!r}")
        if seg == "+":
            if i < last_idx - 1:
                raise ConfigError(
                    f"+ wildcard allowed only in last or last-but-one "
                    f"segment: {topic!r}"
                )
        elif "+" in seg:
            raise ConfigError(f"bad '+' placement: {topic!r}")


def _validate_handler_path(relpath: str) -> None:
    """Validate a handler path — relative, ``.py``, no traversal.

    Traversal (``..``) and absolute paths raise :class:`SandboxEscape`
    — that's the framework's sandbox contract (spec §A.7.3). Shape
    errors (non-``.py`` suffix, empty, wrong slash) raise
    :class:`ConfigError` — those are just request-validation issues.
    """
    if not isinstance(relpath, str) or not relpath:
        raise ConfigError(f"handler path must be non-empty string: {relpath!r}")
    # Traversal / absolute → SandboxEscape (not ConfigError). The
    # spec §A.7.3 lists the escape check first and treats it as a
    # sandbox violation.
    if (
        relpath.startswith("/")
        or PureWindowsPath(relpath).is_absolute()
        or any(part == ".." for part in relpath.split("/"))
    ):
        raise SandboxEscape(f"handler path escapes sandbox: {relpath!r}")
    if "\\" in relpath:
        raise ConfigError(f"handler path must use '/' not '\\': {relpath!r}")
    # __init__.py is explicitly allowed; other files must end in .py.
    if relpath == "__init__.py":
        return
    if not relpath.endswith(".py"):
        raise ConfigError(
            f"handler path must end in .py (or be __init__.py): {relpath!r}"
        )


def _validate_ltm_filename(filename: str) -> None:
    """Validate an LTM filename — relative, ``.md``, no traversal.

    Traversal and absolute paths raise :class:`SandboxEscape`; shape
    errors raise :class:`ConfigError`.
    """
    if not isinstance(filename, str) or not filename:
        raise ConfigError(f"ltm filename must be non-empty string: {filename!r}")
    if (
        PureWindowsPath(filename).is_absolute()
        or PurePosixPath(filename).is_absolute()
        or any(part == ".." for part in Path(filename).parts)
    ):
        raise SandboxEscape(f"ltm filename escapes sandbox: {filename!r}")
    if not filename.endswith(".md"):
        raise ConfigError(f"ltm filename must end in .md: {filename!r}")


def _validate_spawn_proposal(p: SpawnProposal) -> None:
    if not _REGION_NAME_RE.fullmatch(p.name):
        raise ConfigError(
            f"invalid region name {p.name!r}: must match "
            f"/^[a-z][a-z0-9_]{{2,30}}$/"
        )
    if not isinstance(p.starter_prompt, str) or not p.starter_prompt.strip():
        raise ConfigError("spawn proposal: starter_prompt must be non-empty")
    for entry in p.initial_subscriptions:
        _validate_topic(entry.topic)


def _atomic_write_text(target: Path, content: str) -> tuple[int, int]:
    """Atomic write-rename of *content* to *target*.

    Uses ``os.replace`` for POSIX + Windows atomicity (both guarantee
    atomic same-filesystem renames). ``os.fsync`` on the temp fd
    before rename so the content is durable before the directory
    entry flips.

    Returns ``(bytes_written, diff_lines)`` where ``diff_lines`` is
    the absolute difference between the new line count and the
    previous one (0 if the file didn't exist).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    encoded = content.encode("utf-8")
    # Write + fsync + replace.
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    # Old line count for the diff metric.
    old_lines = 0
    if target.exists():
        with target.open("r", encoding="utf-8") as fh:
            old_lines = sum(1 for _ in fh)
    os.replace(str(tmp), str(target))
    new_lines = content.count("\n") + (
        0 if content.endswith("\n") or not content else 1
    )
    return len(encoded), abs(new_lines - old_lines)


def _dump_yaml(data: Any) -> str:
    """Serialize *data* to a YAML string via ``ruamel.yaml``."""
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def _syntax_check(
    *,
    handlers_dir: Path,
    proposed_writes: list[tuple[Path, str]],
    deleted_paths: set[Path],
) -> str | None:
    """Run :func:`ast.parse` on every .py file that would exist after
    applying *proposed_writes* + *deleted_paths*.

    Returns ``None`` on success or a ``"syntax: ..."`` error string
    describing the first failure.
    """
    # Overlay: proposed writes shadow any existing file.
    write_map: dict[Path, str] = {p: c for p, c in proposed_writes}

    # Step 1: any proposed writes that fail to parse.
    for target, content in proposed_writes:
        if not target.name.endswith(".py"):
            continue
        try:
            ast.parse(content, filename=str(target))
        except SyntaxError as exc:
            return f"syntax: {exc.msg} at {target.name}:{exc.lineno}"

    # Step 2: existing files on disk that are neither overwritten nor
    # deleted. Re-parse them too (they should already be valid, but
    # this is the spec: "ast.parse is run on every .py file").
    if handlers_dir.exists():
        for p in handlers_dir.rglob("*.py"):
            if p in write_map or p in deleted_paths:
                continue
            try:
                ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            except SyntaxError as exc:
                return f"syntax: {exc.msg} at {p.name}:{exc.lineno}"
    return None
