"""glia/spawn_executor.py — 8-step spawn pipeline (spec §E.11, Task 5.7a).

Executes ACC-approved spawn requests that arrive on
``hive/system/spawn/request``. The pipeline:

1.  Schema-validate the payload against ``application/hive+spawn-request``
    (spec §B.3.9).  ACL already blocks non-ACC publishers; a schema failure
    publishes a metacog error and a ``hive/system/spawn/failed`` envelope.
2.  Name uniqueness: reject if ``regions/<name>/`` exists or the name is
    already in ``regions_registry.yaml`` (reserved names included).
3.  Scaffold ``regions/<name>/``:
        - ``config.yaml`` derived from the payload,
        - ``prompt.md = starter_prompt``,
        - ``subscriptions.yaml`` from ``initial_subscriptions``,
        - empty ``handlers/__init__.py``,
        - ``memory/stm.json`` empty skeleton (§G.2),
        - ``memory/ltm/.gitkeep``,
        - ``git init`` + initial commit inside the new region directory.
4.  Copy ``bus/acl_templates/_new_region_stub.j2`` to
    ``bus/acl_templates/<name>.j2``.
5.  Invoke ``AclManager.render_and_apply()`` to rebuild ``bus/acl.conf``
    and SIGHUP mosquitto.
6.  ``Launcher.launch_region(name)`` (wrapped in :func:`asyncio.to_thread`).
    Note: spec §E.11 names this ``launcher.start``; the Launcher API uses
    ``launch_region``.  Same semantics.
7.  Publish ``hive/system/spawn/complete`` with ``name``, ``commit_sha`` and
    the originating ``correlation_id`` copied from the request.
8.  Append to a rolling 100-event in-memory log, exposed via
    ``hive/system/spawn/query`` → ``hive/system/spawn/query_response``.

On any step-2..6 failure the pipeline runs cleanup: ``rm -rf`` the new region
directory, delete the new ACL template, publish ``spawn/failed`` with the
reason + correlation_id, and append a failed log entry.

v0 deviations (documented)
--------------------------
**Step 3 — config.yaml serialisation**: the spec mentions a
``config_loader.serialize`` helper that does not exist in the codebase.
Step 3 therefore uses a direct ``ruamel.yaml`` dump instead.  The dumped
shape matches the region_template config schema exactly.

**ACL stub parameterisation**: the spec says the ACL stub is "parameterized
by ``initial_subscriptions``".  The existing ``_new_region_stub.j2`` only
references ``{{ region }}`` and grants the region's own
``hive/cognitive/<region>/#`` namespace (read+write).  We therefore copy the
stub **verbatim** — subscriptions outside the region's own namespace are
blocked by ACL until an approved code-change amends the per-region template.
Subscriptions inside the cognitive namespace work out of the box.

This is a conscious v0 reduction: it keeps the pipeline deterministic, avoids
a brittle Jinja/regex expansion of arbitrary topic strings, and honours
Principle XIV (least privilege — add grants explicitly via code-change).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import structlog
from ruamel.yaml import YAML

from glia.acl_manager import AclManager
from glia.launcher import GliaError, Launcher
from glia.registry import RegionRegistry
from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Topic constants (also re-exported from shared/topics.py)
# ---------------------------------------------------------------------------

TOPIC_SPAWN_COMPLETE = "hive/system/spawn/complete"
TOPIC_SPAWN_FAILED = "hive/system/spawn/failed"
TOPIC_SPAWN_QUERY_RESPONSE = "hive/system/spawn/query_response"
METACOG_ERROR_DETECTED = "hive/metacognition/error/detected"

STUB_TEMPLATE_NAME = "_new_region_stub.j2"

_DEFAULT_LOG_SIZE = 100


# ---------------------------------------------------------------------------
# Schema — mirrors spec §B.3.9 application/hive+spawn-request
# ---------------------------------------------------------------------------

SPAWN_REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "name",
        "role",
        "llm",
        "capabilities",
        "starter_prompt",
        "initial_subscriptions",
    ],
    "properties": {
        "name": {
            "type": "string",
            "pattern": r"^[a-z][a-z0-9_]{2,30}$",
        },
        "role": {
            "type": "string",
            "minLength": 10,
            "maxLength": 500,
        },
        "modality": {"type": ["string", "null"]},
        "llm": {
            "type": "object",
            "required": ["provider", "model"],
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "params": {"type": "object"},
            },
        },
        "capabilities": {
            "type": "object",
            "required": ["self_modify", "tool_use", "vision", "audio"],
            "properties": {
                "self_modify": {"type": "boolean"},
                "tool_use": {"enum": ["none", "basic", "advanced"]},
                "vision": {"type": "boolean"},
                "audio": {"type": "boolean"},
                "stream": {"type": "boolean"},
                "can_spawn": {"type": "boolean"},
                "modalities": {
                    "type": "array",
                    "items": {
                        "enum": [
                            "text",
                            "vision",
                            "audio",
                            "motor",
                            "smell",
                            "haptic",
                        ]
                    },
                },
            },
        },
        "starter_prompt": {"type": "string", "minLength": 100},
        "initial_subscriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["topic", "qos"],
                "properties": {
                    "topic": {"type": "string"},
                    "qos": {"enum": [0, 1]},
                    "description": {"type": "string"},
                },
            },
        },
        "approved_by_acc": {"type": "string", "format": "uuid"},
    },
}

_SCHEMA_VALIDATOR = jsonschema.Draft202012Validator(SPAWN_REQUEST_SCHEMA)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpawnLogEntry:
    """One entry in the rolling spawn log."""

    name: str
    ok: bool
    change_id: str | None  # approved_by_acc uuid
    correlation_id: str | None
    commit_sha: str | None
    reason: str | None
    timestamp: str


# Type alias for the injected subprocess runner.
_Runner = Callable[..., "subprocess.CompletedProcess[str]"]


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class SpawnExecutor:
    """Executes approved spawn requests from ACC.

    Parameters
    ----------
    launcher:
        Sync :class:`Launcher` used to start the new region container.
    registry:
        Region registry — consulted for name uniqueness (includes reserved).
    acl_manager:
        Produces ``bus/acl.conf`` from per-region Jinja templates.
    publish:
        Awaitable publish function (typically ``MqttClient.publish``).
    regions_root:
        Directory containing per-region checkouts.  Tests inject ``tmp_path``.
    acl_templates_dir:
        Directory containing ``_new_region_stub.j2`` and per-region templates.
    runner:
        Subprocess runner — defaults to :func:`subprocess.run`.
    log_size:
        Rolling log capacity; spec §E.11 step 8 says 100.
    """

    def __init__(
        self,
        launcher: Launcher,
        registry: RegionRegistry,
        acl_manager: AclManager,
        *,
        publish: Callable[[Envelope], Awaitable[None]],
        regions_root: Path = Path("regions"),
        acl_templates_dir: Path = Path("bus/acl_templates"),
        runner: _Runner = subprocess.run,
        log_size: int = _DEFAULT_LOG_SIZE,
    ) -> None:
        self._launcher = launcher
        self._registry = registry
        self._acl_manager = acl_manager
        self._publish = publish
        self._regions_root = Path(regions_root)
        self._acl_templates_dir = Path(acl_templates_dir)
        self._runner = runner
        self._log: deque[SpawnLogEntry] = deque(maxlen=log_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_entries(self) -> list[SpawnLogEntry]:
        """Snapshot of the rolling log, oldest first."""
        return list(self._log)

    async def handle_request(self, envelope: Envelope) -> SpawnLogEntry:
        """Execute the 8-step pipeline for a spawn/request envelope.

        Never raises — all failure modes are recorded in the returned
        :class:`SpawnLogEntry` and surfaced via ``spawn/failed`` + metacog
        error events.
        """
        corr_id = envelope.correlation_id
        data = envelope.payload.data if isinstance(envelope.payload.data, dict) else {}

        # --- Step 1: schema validation ---
        try:
            _SCHEMA_VALIDATOR.validate(data)
        except jsonschema.ValidationError as exc:
            reason = f"spawn request schema invalid: {exc.message}"
            log.warning(
                "spawn.schema_invalid",
                reason=reason,
                correlation_id=corr_id,
            )
            await self._publish_metacog_error(
                kind="spawn_schema_invalid",
                detail=reason,
                correlation_id=corr_id,
            )
            return await self._record_failure(
                name=str(data.get("name", "<unknown>")),
                correlation_id=corr_id,
                change_id=data.get("approved_by_acc"),
                reason=reason,
            )

        name: str = data["name"]
        change_id = data.get("approved_by_acc")

        # --- Steps 2-6 inside try/except for cleanup ---
        acl_template_written = False
        try:
            self._check_name_unique(name)
            commit_sha = self._scaffold_region(name, data)
            self._add_acl_template(name)
            acl_template_written = True
            acl_result = await self._acl_manager.render_and_apply()
            if not acl_result.ok:
                raise GliaError(
                    f"ACL render_and_apply failed: {acl_result.reason}"
                )
            await asyncio.to_thread(self._launcher.launch_region, name)
        except (GliaError, OSError, subprocess.SubprocessError) as exc:
            reason = f"spawn failed for {name!r}: {exc}"
            log.error(
                "spawn.failed",
                region=name,
                reason=reason,
                correlation_id=corr_id,
            )
            # Cleanup: rm -rf the region dir + delete the ACL template
            self._cleanup(name, acl_template_written=acl_template_written)
            await self._publish_metacog_error(
                kind="spawn_failed",
                detail=reason,
                correlation_id=corr_id,
                context={"region": name},
            )
            return await self._record_failure(
                name=name,
                correlation_id=corr_id,
                change_id=change_id,
                reason=reason,
            )
        except asyncio.CancelledError:
            # Clean up half-scaffolded state but do not publish (caller is
            # mid-cancel; broker may be unavailable or partially torn down).
            self._cleanup(name, acl_template_written=acl_template_written)
            raise  # propagate cancellation

        # --- Step 7: publish complete ---
        await self._publish_quiet(
            Envelope.new(
                source_region="glia",
                topic=TOPIC_SPAWN_COMPLETE,
                content_type="application/json",
                data={
                    "name": name,
                    "commit_sha": commit_sha,
                    "approved_by_acc": change_id,
                },
                correlation_id=corr_id,
            )
        )

        # --- Step 8: log ---
        entry = SpawnLogEntry(
            name=name,
            ok=True,
            change_id=change_id,
            correlation_id=corr_id,
            commit_sha=commit_sha,
            reason=None,
            timestamp=_utc_now_iso(),
        )
        self._log.append(entry)
        log.info(
            "spawn.ok",
            region=name,
            commit_sha=commit_sha,
            correlation_id=corr_id,
        )
        return entry

    async def handle_query(self, envelope: Envelope) -> None:
        """Respond to ``hive/system/spawn/query`` with matching log entries.

        Filter fields (all optional):
          * ``name``: exact match against :attr:`SpawnLogEntry.name`.
          * ``correlation_id``: exact match against the request's
            ``correlation_id``.

        The response is published to ``hive/system/spawn/query_response``
        with the *request's* ``correlation_id`` so the caller can match
        response→request.
        """
        data = envelope.payload.data if isinstance(envelope.payload.data, dict) else {}
        name_filter = data.get("name")
        corr_filter = data.get("correlation_id")

        matches: Iterable[SpawnLogEntry] = self._log
        if name_filter is not None:
            matches = (e for e in matches if e.name == name_filter)
        if corr_filter is not None:
            matches = (e for e in matches if e.correlation_id == corr_filter)

        entries_payload = [asdict(e) for e in matches]

        await self._publish_quiet(
            Envelope.new(
                source_region="glia",
                topic=TOPIC_SPAWN_QUERY_RESPONSE,
                content_type="application/json",
                data={"entries": entries_payload},
                correlation_id=envelope.correlation_id,
            )
        )

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _check_name_unique(self, name: str) -> None:
        """Step 2 — reject duplicate or reserved names."""
        if (self._regions_root / name).exists():
            raise GliaError(f"region {name!r} already exists on disk")
        if name in self._registry:
            raise GliaError(
                f"region {name!r} already in registry (reserved or active)"
            )

    def _scaffold_region(self, name: str, data: dict[str, Any]) -> str:
        """Step 3 — create the region directory and return initial commit sha."""
        region_dir = self._regions_root / name
        region_dir.mkdir(parents=True, exist_ok=False)

        # config.yaml
        cfg = _build_region_config(name, data)
        yaml = YAML(typ="safe")
        yaml.default_flow_style = False
        with (region_dir / "config.yaml").open("w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh)

        # prompt.md
        (region_dir / "prompt.md").write_text(
            data["starter_prompt"], encoding="utf-8"
        )

        # subscriptions.yaml
        with (region_dir / "subscriptions.yaml").open(
            "w", encoding="utf-8"
        ) as fh:
            yaml.dump(list(data["initial_subscriptions"]), fh)

        # handlers/__init__.py
        handlers_dir = region_dir / "handlers"
        handlers_dir.mkdir()
        (handlers_dir / "__init__.py").write_text("", encoding="utf-8")

        # memory/stm.json + memory/ltm/.gitkeep
        mem_dir = region_dir / "memory"
        (mem_dir / "ltm").mkdir(parents=True)
        (mem_dir / "ltm" / ".gitkeep").write_text("", encoding="utf-8")
        (mem_dir / "stm.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "region": name,
                    "updated_at": _utc_now_iso(),
                    "slots": {},
                    "recent_events": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # git init + add + commit + rev-parse
        self._run_git(region_dir, ["git", "init"])
        self._run_git(region_dir, ["git", "add", "."])
        self._run_git(
            region_dir,
            ["git", "commit", "-m", f"spawn: initial commit for {name}"],
        )
        rev = self._runner(
            ["git", "rev-parse", "HEAD"],
            cwd=region_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        sha = (rev.stdout or "").strip()
        if rev.returncode != 0 or not sha:
            raise GliaError(
                f"git rev-parse HEAD failed in {region_dir}: "
                f"rc={rev.returncode} stderr={rev.stderr!r}"
            )
        return sha

    def _add_acl_template(self, name: str) -> None:
        """Step 4 — copy _new_region_stub.j2 to <name>.j2."""
        src = self._acl_templates_dir / STUB_TEMPLATE_NAME
        dst = self._acl_templates_dir / f"{name}.j2"
        if not src.exists():
            raise GliaError(f"ACL stub template not found at {src}")
        shutil.copy(src, dst)

    def _cleanup(self, name: str, *, acl_template_written: bool) -> None:
        """Remove scaffolded files when the pipeline fails mid-flight.

        Idempotent: tolerates partial state.
        """
        region_dir = self._regions_root / name
        if region_dir.exists():
            shutil.rmtree(region_dir, ignore_errors=True)
        if acl_template_written:
            tmpl = self._acl_templates_dir / f"{name}.j2"
            try:
                tmpl.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                # Best-effort cleanup — log and move on.
                log.warning(
                    "spawn.cleanup_template_failed",
                    template=str(tmpl),
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_git(self, cwd: Path, cmd: list[str]) -> None:
        """Run a git subcommand; raise GliaError on non-zero."""
        result = self._runner(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GliaError(
                f"{' '.join(cmd)} failed in {cwd}: "
                f"rc={result.returncode} stderr={result.stderr!r}"
            )

    async def _record_failure(
        self,
        *,
        name: str,
        correlation_id: str | None,
        change_id: str | None,
        reason: str,
    ) -> SpawnLogEntry:
        """Publish spawn/failed, append a failed log entry, return it."""
        await self._publish_quiet(
            Envelope.new(
                source_region="glia",
                topic=TOPIC_SPAWN_FAILED,
                content_type="application/json",
                data={
                    "name": name,
                    "reason": reason,
                    "approved_by_acc": change_id,
                },
                correlation_id=correlation_id,
            )
        )
        entry = SpawnLogEntry(
            name=name,
            ok=False,
            change_id=change_id,
            correlation_id=correlation_id,
            commit_sha=None,
            reason=reason,
            timestamp=_utc_now_iso(),
        )
        self._log.append(entry)
        return entry

    async def _publish_metacog_error(
        self,
        *,
        kind: str,
        detail: str,
        correlation_id: str | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if correlation_id is not None:
            ctx.setdefault("correlation_id", correlation_id)
        await self._publish_quiet(
            Envelope.new(
                source_region="glia",
                topic=METACOG_ERROR_DETECTED,
                content_type="application/json",
                data={"kind": kind, "detail": detail, "context": ctx},
                correlation_id=correlation_id,
            )
        )

    async def _publish_quiet(self, envelope: Envelope) -> None:
        """Publish; log + swallow any broker error so the main outcome stands."""
        try:
            await self._publish(envelope)
        except Exception as exc:  # noqa: BLE001 — deliberately broad
            log.warning(
                "spawn.publish_failed",
                topic=envelope.topic,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """UTC ISO timestamp with millisecond precision (matches Envelope)."""
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _build_region_config(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a region ``config.yaml`` dict from the spawn payload.

    Only the fields REQUIRED by ``region_template/config_schema.json`` are
    written; framework defaults (lifecycle, memory, dispatch, mqtt, logging)
    come from ``region_template/defaults.yaml`` at load time.
    """
    caps = dict(data["capabilities"])
    # Ensure required capability fields have sane defaults if the schema's
    # 'required' list grows beyond the four currently mandated.
    caps.setdefault("self_modify", False)
    caps.setdefault("tool_use", "none")
    caps.setdefault("vision", False)
    caps.setdefault("audio", False)

    llm_in = data["llm"]
    llm_out: dict[str, Any] = {
        "provider": llm_in["provider"],
        "model": llm_in["model"],
    }
    if "params" in llm_in:
        llm_out["params"] = dict(llm_in["params"])

    return {
        "schema_version": 1,
        "name": name,
        "role": data["role"],
        "llm": llm_out,
        "capabilities": caps,
    }
