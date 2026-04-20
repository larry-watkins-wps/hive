# region_template/errors.py
"""Hive error hierarchy — spec §A.9."""
from __future__ import annotations

from typing import Any


class HiveError(Exception):
    """Base."""


class ConfigError(HiveError):
    """config.yaml invalid or missing. Exit 2. Glia does NOT restart."""


class ConnectionError(HiveError):  # shadows builtin; fully-qualified only
    """MQTT unreachable after retries. Exit 4. Glia restarts with backoff."""


class CapabilityDenied(HiveError):
    """Tool call made without declared capability. Runtime-local."""


class PhaseViolation(HiveError):
    """Sleep-only tool called during wake (or vice versa)."""


class HandlerError(HiveError):
    """Base for handler-raised errors."""


class SandboxEscape(HiveError):
    """Tool attempted to write outside regions/<name>/. Fatal; crashes the region."""


class LlmError(HiveError):
    """Wraps LiteLLM exceptions; has .retryable attribute."""

    def __init__(self, *args: Any, retryable: bool = False) -> None:
        super().__init__(*args)
        self.retryable = retryable


class GitError(HiveError):
    """Per-region git operation failed."""


class StmOverflow(HiveError):
    """STM write would exceed configured max."""


# Classification:
#
# | Error                               | Phase caught | Action
# |-------------------------------------|--------------|-------------------------------------
# | ConfigError, ConnectionError,       | any          | Fatal, exit nonzero
# |   GitError, SandboxEscape           |              |
# | CapabilityDenied, PhaseViolation    | runtime      | Return error to caller; log INFO
# | LlmError (retryable)                | runtime      | Retry per C.5; eventual fail → metacog
# | LlmError (non-retryable)            | runtime      | Publish metacog error; continue
# | HandlerError                        | dispatch     | Log, publish metacog error, continue
# | StmOverflow                         | dispatch     | Force sleep trigger; fail current write
