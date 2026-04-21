"""Sandboxed filesystem reader for per-region disk access.

Single entry point for observatory/api.py v2 routes. Every read runs through
_validate() which rejects symlinks, traversal, absolute paths, null bytes,
malformed region names, missing files, and files larger than MAX_FILE_BYTES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024
_REGION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SandboxError(Exception):
    """Raised when a region-file read violates sandbox rules.

    `code` is the HTTP status an API handler should emit: 403 sandbox, 404
    missing, 413 oversize, 502 parse failure.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HandlerEntry:
    path: str  # POSIX path relative to `regions_root / region`
    size: int  # bytes


class RegionReader:
    """Sandboxed reader. Instantiated once at service startup."""

    def __init__(self, regions_root: Path) -> None:
        self._root = regions_root.resolve()
        if not self._root.exists() or not self._root.is_dir():
            raise FileNotFoundError(f"regions_root does not exist: {self._root}")

    def read_prompt(self, region: str) -> str:
        path = self._validate(region, "prompt.md")
        return path.read_text(encoding="utf-8")

    # --- stubs for Task 2/3 ---
    def read_stm(self, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def read_subscriptions(self, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def read_config(self, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def list_handlers(self, region: str) -> list[HandlerEntry]:
        raise NotImplementedError

    # --- internal ---
    def _validate(self, region: str, rel: str) -> Path:
        """Run the full sandbox pipeline; return an absolute, safe Path."""
        if not _REGION_NAME_RE.fullmatch(region):
            raise SandboxError(f"invalid region name: {region!r}", 404)
        # Pre-resolve component checks
        if "\x00" in rel or "\x00" in region:
            raise SandboxError("null byte in path", 403)
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise SandboxError("traversal or absolute path rejected", 403)

        candidate = (self._root / region / rel).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as e:
            raise SandboxError("path escapes sandbox", 403) from e

        # Reject if the leaf component is a symlink. This is a defense-in-depth
        # check on top of the `relative_to` guard above: any symlink that points
        # *outside* the sandbox is already rejected by the escape check, so this
        # exists to also reject symlinks that stay inside the sandbox (cycle /
        # DoS concerns). Only the leaf is checked here — per-component checks
        # for multi-segment `rel` inputs (e.g. Task 2's `list_handlers` entries)
        # will run through this same pipeline one-by-one.
        unresolved = self._root / region / rel
        try:
            if unresolved.is_symlink():
                raise SandboxError("symlink rejected", 403)
        except OSError as e:
            raise SandboxError(f"stat failed: {e}", 403) from e

        if not candidate.exists() or not candidate.is_file():
            raise SandboxError(f"file not found: {region}/{rel}", 404)

        if candidate.stat().st_size > MAX_FILE_BYTES:
            raise SandboxError(
                f"file exceeds {MAX_FILE_BYTES} bytes: {region}/{rel}", 413,
            )

        log.debug(
            "observatory.region_read",
            region=region,
            file=rel,
            size_bytes=candidate.stat().st_size,
        )
        return candidate
