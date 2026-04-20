"""glia/codechange_executor.py — DNA-layer code-change executor (spec §E.10).

Applies an ACC-approved, human-cosigned patch to ``region_template/``
(the "DNA"), rebuilds ``hive-region:v0``, and rolling-restarts affected
region containers.  This is the **one** code path that writes to
``region_template/`` at runtime.

v0 scope reductions (vs. the full spec)
---------------------------------------
* **No sidecar container.**  We run ``git apply`` directly in the running
  glia container, which bind-mounts ``region_template/`` RW.  Spec §E.10 calls
  for a short-lived privileged container; that is deferred.
* **Serial restart, no exponential stagger.**  Each affected region is
  restarted in turn with a simple ``asyncio.sleep(restart_stagger_s)`` between
  them to give the broker grace; no back-off curve.
* **Tag-based rollback.**  On restart failure we re-tag
  ``hive-region:v0-prev`` back to ``hive-region:v0`` and relaunch
  already-restarted-and-subsequent regions.  This assumes the ``-prev`` tag
  still exists (first-ever codechange has no prior tag — the failure mode is
  documented and surfaced via the metacog event).
* **Cosign signature field name.**  The spec's JSON block lists
  ``human_cosigner`` (the identity) but not the signature blob.  We accept
  ``cosign_signature`` on the payload.  A missing field rejects per
  §E.10 step 1.

Flow summary
------------
1. Validate payload: require ``change_id``, ``patch``, ``cosign_signature``,
   ``affected_regions``.
2. Cosign-verify via injected ``cosign_verifier`` (defaults to
   ``cosign verify-blob`` with ``HIVE_HUMAN_COSIGN_PUBKEY[_PATH]``).
3. ``git apply --check`` against ``region_template_dir`` — abort on
   non-zero.
4. ``git apply`` for real — abort on non-zero.
5. Tag current ``hive-region:v0`` → ``hive-region:v0-prev``; build new image.
   Build failure → ``git checkout .`` to revert patch + publish rollback.
6. Serial restart loop with stagger.  A restart failure triggers image
   rollback (re-tag -prev back) + relaunch of failed and subsequent regions.
7. Publish ``codechange_{complete,rejected,rollback}`` metacog events on
   every terminal state.

All metacog events use topic ``hive/metacognition/error/detected`` with
``data = {"kind": "<event>", "detail": "...", "context": {...}}``.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from glia.launcher import GliaError, Launcher
from glia.registry import RegionRegistry
from shared.message_envelope import Envelope
from shared.topics import METACOGNITION_ERROR_DETECTED

log = structlog.get_logger(__name__)


REGION_TEMPLATE_DIR = Path("/hive/region_template")
REPO_ROOT = Path("/hive")
REGION_IMAGE = "hive-region:v0"
REGION_IMAGE_REPO = "hive-region"
REGION_IMAGE_TAG = "v0"
REGION_IMAGE_PREV_TAG = "v0-prev"

_REQUIRED_PAYLOAD_FIELDS: tuple[str, ...] = (
    "change_id",
    "patch",
    "cosign_signature",
    "affected_regions",
)


@dataclass(frozen=True)
class CodeChangeResult:
    """Outcome of a single :meth:`CodeChangeExecutor.apply_change` call."""

    ok: bool
    change_id: str
    reason: str | None = None


class CodeChangeError(GliaError):
    """Recoverable code-change executor failure."""


_Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class CodeChangeExecutor:
    """Applies approved DNA codechanges: patch → rebuild → rolling restart."""

    def __init__(
        self,
        launcher: Launcher,
        registry: RegionRegistry,
        *,
        publish: Callable[[Envelope], Awaitable[None]],
        cosign_verifier: Callable[[str, str], bool] | None = None,
        docker_client: Any | None = None,
        region_template_dir: Path = REGION_TEMPLATE_DIR,
        repo_root: Path = REPO_ROOT,
        runner: _Runner = subprocess.run,
        restart_stagger_s: float = 2.0,
    ) -> None:
        self._launcher = launcher
        self._registry = registry
        self._publish = publish
        self._cosign_verifier = cosign_verifier or self._default_cosign_verifier
        self._docker = docker_client
        self._region_template_dir = region_template_dir
        self._repo_root = repo_root
        self._runner = runner
        self._stagger_s = restart_stagger_s

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def apply_change(self, envelope: Envelope) -> CodeChangeResult:  # noqa: PLR0911 — each branch is a distinct terminal outcome of the step sequence
        """Execute the approved codechange end-to-end."""
        data = envelope.payload.data if isinstance(envelope.payload.data, dict) else {}
        change_id = data.get("change_id", "<unknown>")

        # 1. Validate payload.
        missing = self._missing_fields(data)
        if missing:
            reason = f"missing_field:{missing[0]}"
            await self._publish_metacog(
                kind="codechange_rejected",
                change_id=change_id,
                detail=f"payload missing required field: {missing[0]}",
                context_extra={"reason": reason, "missing_fields": list(missing)},
            )
            return CodeChangeResult(ok=False, change_id=change_id, reason=reason)

        patch_text: str = data["patch"]
        signature: str = data["cosign_signature"]
        affected_raw: list[str] = list(data["affected_regions"])

        # 2. Cosign verify.
        if not self._cosign_verifier(patch_text, signature):
            await self._publish_metacog(
                kind="codechange_rejected",
                change_id=change_id,
                detail="cosign verification failed",
                context_extra={"reason": "invalid_cosign"},
            )
            return CodeChangeResult(
                ok=False, change_id=change_id, reason="invalid_cosign"
            )

        # 3. Dry-run patch.
        if not self._dry_run_patch(patch_text):
            await self._publish_metacog(
                kind="codechange_rejected",
                change_id=change_id,
                detail="git apply --check failed",
                context_extra={"reason": "malformed_patch"},
            )
            return CodeChangeResult(
                ok=False, change_id=change_id, reason="malformed_patch"
            )

        # 4. Real apply.
        try:
            self._apply_patch(patch_text)
        except CodeChangeError as exc:
            await self._publish_metacog(
                kind="codechange_rejected",
                change_id=change_id,
                detail=f"git apply failed: {exc}",
                context_extra={"reason": "patch_apply_failed"},
            )
            return CodeChangeResult(
                ok=False, change_id=change_id, reason="patch_apply_failed"
            )

        # 5. Rebuild image.
        try:
            self._rebuild_image()
        except Exception as exc:  # noqa: BLE001 — docker SDK raises arbitrary
            log.error(
                "codechange.build_failed",
                change_id=change_id,
                error=str(exc),
            )
            self._revert_patch()
            await self._publish_metacog(
                kind="codechange_rollback",
                change_id=change_id,
                detail=f"build failed: {exc}",
                context_extra={"reason": "build_failed"},
            )
            return CodeChangeResult(
                ok=False, change_id=change_id, reason="build_failed"
            )

        # 6. Rolling restart.
        affected = self._resolve_affected(affected_raw)
        try:
            await self._restart_affected(affected)
        except CodeChangeError as exc:
            log.error(
                "codechange.restart_failed",
                change_id=change_id,
                error=str(exc),
            )
            # Roll image back, relaunch ALL affected regions on the old tag.
            # Regions 0..failed_index-1 were already restarted on the NEW image;
            # bouncing them again on the rolled-back image is cheap and
            # idempotent (spec §E.10 step 5).
            self._rollback_image()
            await self._restart_on_rollback(affected)
            await self._publish_metacog(
                kind="codechange_rollback",
                change_id=change_id,
                detail=f"restart failed: {exc}",
                context_extra={
                    "reason": "restart_failed",
                    "failed_region": getattr(exc, "failed_region", None),
                },
            )
            return CodeChangeResult(
                ok=False, change_id=change_id, reason="restart_failed"
            )

        # 7. Success.
        await self._publish_metacog(
            kind="codechange_complete",
            change_id=change_id,
            detail=f"applied codechange {change_id}",
            context_extra={
                "affected_regions": affected,
                "new_tag": REGION_IMAGE,
            },
        )
        return CodeChangeResult(ok=True, change_id=change_id)

    # ------------------------------------------------------------------
    # Payload / resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _missing_fields(data: dict[str, Any]) -> list[str]:
        # Key-absent check (not falsy) — empty strings for ``patch`` or
        # ``change_id`` should fall through to downstream validation which
        # will surface a clearer error (e.g. the patch dry-run will reject
        # an empty patch explicitly).
        return [
            f for f in _REQUIRED_PAYLOAD_FIELDS
            if f not in data or data.get(f) is None
        ]

    def _resolve_affected(self, affected: list[str]) -> list[str]:
        """Expand ``["*"]`` into the registry's active region names."""
        if "*" in affected:
            return [e.name for e in self._registry.active()]
        return list(affected)

    # ------------------------------------------------------------------
    # Patch steps
    # ------------------------------------------------------------------

    def _dry_run_patch(self, patch_text: str) -> bool:
        """git apply --check - (stdin).  True if clean."""
        result = self._runner(
            ["git", "apply", "--check", "-"],
            cwd=self._region_template_dir,
            input=patch_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            log.warning(
                "codechange.dry_run_failed",
                stderr=(result.stderr or "").strip(),
            )
        return result.returncode == 0

    def _apply_patch(self, patch_text: str) -> None:
        """git apply - (stdin).  Raises :class:`CodeChangeError` on failure.

        Assumes the patch's ``a/`` and ``b/`` paths are repo-root relative.
        The patch is fed via stdin and applied with
        ``cwd=region_template_dir``; paths inside the patch must be relative
        to the git repo root for ``git apply`` to locate them correctly.
        """
        result = self._runner(
            ["git", "apply", "-"],
            cwd=self._region_template_dir,
            input=patch_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CodeChangeError(
                f"git apply failed: {(result.stderr or '').strip()}"
            )

    def _revert_patch(self) -> None:
        """Undo a successfully-applied patch by checking out region_template/.

        Runs ``git checkout -- <region_template_path>`` from the repo root,
        scoping the revert precisely to the DNA path.
        """
        try:
            rel = self._region_template_dir.relative_to(self._repo_root)
        except ValueError:
            rel = self._region_template_dir
        try:
            self._runner(
                ["git", "checkout", "--", str(rel)],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("codechange.revert_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Image steps
    # ------------------------------------------------------------------

    def _rebuild_image(self) -> None:
        """Tag current image as ``-prev`` then rebuild ``hive-region:v0``."""
        if self._docker is None:
            raise CodeChangeError("docker client not configured")

        # Tag previous image (best-effort — ignore if :v0 doesn't exist yet).
        try:
            self._docker.api.tag(
                REGION_IMAGE, REGION_IMAGE_REPO, REGION_IMAGE_PREV_TAG
            )
        except Exception as exc:  # noqa: BLE001 — first-ever build has no v0
            log.warning("codechange.prev_tag_skipped", error=str(exc))

        # Build new image.
        self._docker.images.build(
            path=str(self._repo_root),
            dockerfile="region_template/Dockerfile",
            tag=REGION_IMAGE,
            rm=True,
        )

    def _rollback_image(self) -> None:
        """Re-tag ``hive-region:v0-prev`` back to ``hive-region:v0``."""
        if self._docker is None:
            return
        try:
            self._docker.api.tag(
                f"{REGION_IMAGE_REPO}:{REGION_IMAGE_PREV_TAG}",
                REGION_IMAGE_REPO,
                REGION_IMAGE_TAG,
                force=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("codechange.image_rollback_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Restart loop
    # ------------------------------------------------------------------

    async def _restart_affected(self, regions: list[str]) -> None:
        """Serial restart with stagger.  Raises :class:`CodeChangeError`.

        The raised error carries ``failed_index`` and ``failed_region`` so
        the caller knows where to resume on rollback.
        """
        for i, name in enumerate(regions):
            if i > 0 and self._stagger_s > 0:
                await asyncio.sleep(self._stagger_s)
            try:
                await asyncio.to_thread(self._launcher.restart_region, name)
            except GliaError as exc:
                err = CodeChangeError(f"region {name} failed to restart: {exc}")
                err.failed_index = i  # type: ignore[attr-defined]
                err.failed_region = name  # type: ignore[attr-defined]
                raise err from exc

    async def _restart_on_rollback(self, regions: list[str]) -> None:
        """Best-effort relaunch of regions on the rolled-back image."""
        for name in regions:
            try:
                await asyncio.to_thread(self._launcher.restart_region, name)
            except GliaError as exc:
                log.error(
                    "codechange.rollback_restart_failed",
                    region=name,
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Cosign
    # ------------------------------------------------------------------

    @staticmethod
    def _default_cosign_verifier(patch_text: str, signature: str) -> bool:
        """Invoke ``cosign verify-blob`` with env-configured pubkey.

        Returns False (never raises) if cosign isn't installed or the env
        var is missing — callers get a clean rejection rather than an
        exception.
        """
        pubkey = (
            os.environ.get("HIVE_HUMAN_COSIGN_PUBKEY_PATH")
            or os.environ.get("HIVE_HUMAN_COSIGN_PUBKEY")
        )
        if not pubkey:
            return False
        pf_path: str | None = None
        sf_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".patch", delete=False
            ) as pf:
                pf.write(patch_text.encode("utf-8"))
                pf_path = pf.name
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".sig", delete=False
            ) as sf:
                sf.write(signature.encode("utf-8"))
                sf_path = sf.name
            result = subprocess.run(
                [
                    "cosign", "verify-blob",
                    "--key", pubkey,
                    "--signature", sf_path,
                    pf_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
        finally:
            if pf_path is not None:
                Path(pf_path).unlink(missing_ok=True)
            if sf_path is not None:
                Path(sf_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def _publish_metacog(
        self,
        *,
        kind: str,
        change_id: str,
        detail: str,
        context_extra: dict[str, Any] | None = None,
    ) -> None:
        """Publish a metacog event; log + swallow broker errors."""
        context: dict[str, Any] = {"change_id": change_id}
        if context_extra:
            context.update(context_extra)
        envelope = Envelope.new(
            source_region="glia",
            topic=METACOGNITION_ERROR_DETECTED,
            content_type="application/json",
            data={"kind": kind, "detail": detail, "context": context},
        )
        try:
            await self._publish(envelope)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "codechange.publish_failed",
                kind=kind,
                change_id=change_id,
                error=str(exc),
            )
