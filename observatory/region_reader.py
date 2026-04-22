"""Sandboxed filesystem reader for per-region disk access.

Single entry point for observatory/api.py v2 routes. Every read runs through
_validate() which rejects symlinks, traversal, absolute paths, null bytes,
malformed region names, missing files, and files larger than MAX_FILE_BYTES.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import structlog
import yaml

log = structlog.get_logger(__name__)

MAX_FILE_BYTES = 2 * 1024 * 1024
_REGION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SandboxError(Exception):
    """Raised when a region-file read violates sandbox rules.

    `code` is the HTTP status an API handler should emit: 403 sandbox, 404
    missing, 413 oversize, 502 parse failure.

    `reason` is a short machine tag matching `_deny`'s taxonomy
    (``invalid_region_name``, ``null_byte``, ``traversal``, ``escape``,
    ``stat_failed``, ``symlink``, ``missing``, ``oversize``, ``parse_json``,
    ``parse_yaml``). Route handlers can discriminate on this without parsing
    the human-readable message string.
    """

    def __init__(self, message: str, code: int, reason: str = "sandbox") -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class HandlerEntry:
    path: str  # POSIX path relative to `regions_root / region`
    size: int  # bytes


class RegionReader:
    """Sandboxed reader. Instantiated once at service startup."""

    _SECRET_SUFFIXES = ("_key", "_token", "_secret")

    @classmethod
    def _redact(cls, obj: Any) -> Any:
        """Walk dicts/lists; replace values whose key ends in a secret suffix.

        Key-suffix match short-circuits: when a dict key ends in a suffix
        (case-insensitive), the whole value is replaced with ``"***"`` and no
        further recursion happens into that value. Lists recurse element-wise.
        """
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                key_s = str(k).lower()
                if any(key_s.endswith(s) for s in cls._SECRET_SUFFIXES):
                    out[k] = "***"
                else:
                    out[k] = cls._redact(v)
            return out
        if isinstance(obj, list):
            return [cls._redact(x) for x in obj]
        return obj

    def __init__(self, regions_root: Path) -> None:
        self._root = regions_root.resolve()
        if not self._root.exists() or not self._root.is_dir():
            raise FileNotFoundError(f"regions_root does not exist: {self._root}")

    def read_prompt(self, region: str) -> str:
        path = self._validate(region, "prompt.md", method="read_prompt")
        return path.read_text(encoding="utf-8")

    def read_stm(self, region: str) -> dict[str, Any]:
        path = self._validate(region, "memory/stm.json", method="read_stm")
        return self._parse_json(region, "memory/stm.json", path)

    def read_subscriptions(self, region: str) -> dict[str, Any]:
        path = self._validate(region, "subscriptions.yaml", method="read_subscriptions")
        return self._parse_yaml(region, "subscriptions.yaml", path)

    def read_config(self, region: str) -> dict[str, Any]:
        path = self._validate(region, "config.yaml", method="read_config")
        parsed = self._parse_yaml(region, "config.yaml", path)
        return self._redact(parsed)

    def read_appendix(self, region: str) -> str | None:
        """Read ``regions/<region>/memory/appendices/rolling.md``.

        Returns ``None`` when the file doesn't exist — a fresh region that
        has never slept legitimately lacks this file. Spec §9.2 specifies
        this signature and the corresponding HTTP 404 body shape
        (``{"error":"appendix_missing","message":"No appendix file for
        region"}``) is assembled by the route.

        Still raises ``SandboxError`` for sandbox violations (403), oversize
        (413), invalid region name (404 + ``reason="invalid_region_name"``),
        or any other non-missing denial. No redaction: appendix content is
        LLM-authored narrative (spec §9.2).
        """
        try:
            path = self._validate(
                region,
                "memory/appendices/rolling.md",
                method="read_appendix",
            )
        except SandboxError as e:
            # _validate emits code=404 for both the "missing" case (file
            # simply doesn't exist yet) and "invalid_region_name". Only the
            # former collapses to a None return — invalid names still raise.
            if e.reason == "missing":
                return None
            raise
        return path.read_text(encoding="utf-8")

    def list_handlers(self, region: str) -> list[HandlerEntry]:
        # Validate the region name first using the same rule as _validate,
        # without needing a specific filename.
        if not _REGION_NAME_RE.fullmatch(region):
            self._deny(region, "handlers", 404, "invalid_region_name",
                       f"invalid region name: {region!r}")

        region_dir = (self._root / region).resolve()
        try:
            region_dir.relative_to(self._root)
        except ValueError:
            self._deny(region, "handlers", 403, "escape", "path escapes sandbox")

        handlers_dir = region_dir / "handlers"
        if not handlers_dir.exists() or not handlers_dir.is_dir():
            return []

        # Walk with follow_symlinks=False so in-sandbox symlinked directories
        # do not silently cause infinite traversal (cycle / DoS) and do not
        # yield .py files whose path string hides a symlink hop. `_validate`
        # in the per-entry loop below also rejects leaf symlinks.
        entries: list[HandlerEntry] = []
        py_paths: list[Path] = []
        for dirpath, _dirnames, filenames in handlers_dir.walk(follow_symlinks=False):
            for fname in filenames:
                if fname.endswith(".py"):
                    py_paths.append(dirpath / fname)
        for py in sorted(py_paths):
            try:
                rel = py.relative_to(region_dir).as_posix()
            except ValueError:
                continue
            # Re-validate through the full pipeline (covers symlinks, null bytes,
            # size cap).
            validated = self._validate(region, rel, method="list_handlers")
            entries.append(HandlerEntry(path=rel, size=validated.stat().st_size))
        return sorted(entries, key=lambda e: e.path)

    # --- internal ---
    def _deny(self, region: str, rel: str, code: int, reason: str, message: str) -> NoReturn:
        """Log the denial and raise SandboxError.

        `reason` is a short machine tag. The complete taxonomy used by the
        pipeline: ``invalid_region_name``, ``null_byte``, ``traversal``,
        ``escape``, ``stat_failed``, ``symlink``, ``missing``, ``oversize``,
        ``parse_json``, ``parse_yaml``. Spec §6.1 requires the
        ``observatory.region_read_denied`` event with keys ``region``,
        ``file``, ``code``, ``reason``.

        Emitted at ``warning`` level (not ``debug``) because sandbox denials
        are security-relevant and should surface in default production log
        configs for prod aggregators to alert on. Successful reads still use
        ``debug`` — they're expected, high-volume, and uninteresting.
        """
        log.warning(
            "observatory.region_read_denied",
            region=region,
            file=rel,
            code=code,
            reason=reason,
        )
        raise SandboxError(message, code, reason=reason)

    def _validate(self, region: str, rel: str, *, method: str) -> Path:
        """Run the full sandbox pipeline; return an absolute, safe Path.

        `method` is the reader method name (e.g. "read_prompt"); spec §6.1
        requires it as a key on the success log event.
        """
        if not _REGION_NAME_RE.fullmatch(region):
            self._deny(region, rel, 404, "invalid_region_name",
                       f"invalid region name: {region!r}")
        if "\x00" in rel or "\x00" in region:
            self._deny(region, rel, 403, "null_byte", "null byte in path")
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            self._deny(region, rel, 403, "traversal",
                       "traversal or absolute path rejected")

        candidate = (self._root / region / rel).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            self._deny(region, rel, 403, "escape", "path escapes sandbox")

        # Reject if the leaf component is a symlink. This is a defense-in-depth
        # check on top of the `relative_to` guard above: any symlink that points
        # *outside* the sandbox is already rejected by the escape check, so this
        # exists to also reject symlinks that stay inside the sandbox (cycle /
        # DoS concerns). Only the leaf is checked here — per-component checks
        # for multi-segment `rel` inputs (e.g. Task 2's `list_handlers` entries)
        # will run through this same pipeline one-by-one.
        unresolved = self._root / region / rel
        try:
            is_link = unresolved.is_symlink()
        except OSError as e:
            self._deny(region, rel, 403, "stat_failed", f"stat failed: {e}")
        if is_link:
            self._deny(region, rel, 403, "symlink", "symlink rejected")

        if not candidate.exists() or not candidate.is_file():
            self._deny(region, rel, 404, "missing",
                       f"file not found: {region}/{rel}")

        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES:
            self._deny(region, rel, 413, "oversize",
                       f"file exceeds {MAX_FILE_BYTES} bytes: {region}/{rel}")

        log.debug(
            "observatory.region_read",
            region=region,
            file=rel,
            size_bytes=size,
            method=method,
        )
        return candidate

    def _parse_json(self, region: str, rel: str, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            self._deny(region, rel, 502, "parse_json",
                       f"JSON parse failure in {path.name}: {e}")

    def _parse_yaml(self, region: str, rel: str, path: Path) -> dict[str, Any]:
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            self._deny(region, rel, 502, "parse_yaml",
                       f"YAML parse failure in {path.name}: {e}")
        return parsed if parsed is not None else {}
