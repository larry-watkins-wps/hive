"""Region config loader — spec §F.5.

Pipeline
--------

1. YAML-load the region's ``config.yaml`` via ``ruamel.yaml``.
2. Deep-merge ``region_template/defaults.yaml`` UNDER the region data. Region
   values win at every leaf. Lists and scalars do not merge — region wins
   entirely; only dicts are recursed into.
3. JSON-schema-validate the merged dict against ``config_schema.json`` (the
   §F.2 contract). Validation failures surface as :class:`ConfigError`.
4. Env interpolation: any scalar string of the form ``${ENV:VAR_NAME}`` is
   replaced with ``os.environ['VAR_NAME']``. Missing vars raise
   :class:`ConfigError`. Note: ``mqtt.password_env`` is a pointer to the env
   var *name* (resolved later by the MQTT adapter), so it stays untouched — it
   does not match the ``${ENV:...}`` pattern unless a region writes
   ``password_env: "${ENV:SOMETHING}"`` explicitly, which is valid but
   unusual.
5. Construct :class:`RegionConfig` (Pydantic v2). This second validation pass
   catches any drift between the JSON schema and the Pydantic model, and
   yields the typed object the rest of the runtime consumes.

Both validation layers are intentional: JSON schema is the spec-level contract
(§F.2), Pydantic gives the typed objects used downstream.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from region_template.errors import ConfigError
from region_template.types import CapabilityProfile

__all__ = [
    "DispatchConfig",
    "LifecycleConfig",
    "LlmBudgets",
    "LlmCaching",
    "LlmConfig",
    "LlmRetry",
    "LoggingConfig",
    "MemoryConfig",
    "MqttConfig",
    "RegionConfig",
    "load_config",
]

# ---------------------------------------------------------------------------
# Pydantic models — mirror §F.2 JSON schema
# ---------------------------------------------------------------------------


class LlmBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_call_max_tokens: int = Field(default=2048, ge=128)
    per_hour_input_tokens: int = Field(default=500_000, ge=1000)
    per_hour_output_tokens: int = Field(default=100_000, ge=1000)
    per_day_cost_usd: float = Field(default=10.0, ge=0)


class LlmRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_s: float = Field(default=1.0, ge=0.1)
    max_backoff_s: float = Field(default=10.0, ge=1)


class LlmCaching(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["none", "system", "system_and_messages"] = "system"
    ttl_hint_s: int = Field(default=300, ge=10)


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    budgets: LlmBudgets = Field(default_factory=LlmBudgets)
    retry: LlmRetry = Field(default_factory=LlmRetry)
    caching: LlmCaching = Field(default_factory=LlmCaching)


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heartbeat_interval_s: int = Field(default=5, ge=1, le=60)
    sleep_quiet_window_s: int = Field(default=300, ge=30)
    sleep_max_wake_s: int = Field(default=3600, ge=60)
    sleep_max_queue_depth: int = Field(default=5, ge=0)
    sleep_abort_cortisol_threshold: float = Field(default=0.85, ge=0, le=1)
    shutdown_timeout_s: int = Field(default=30, ge=5)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stm_max_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    recent_events_max: int = Field(default=200, ge=10)
    ltm_query_default_k: int = Field(default=5, ge=1, le=50)
    index_rebuild_interval_sleeps: int = Field(default=10, ge=1)


class DispatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handler_concurrency_limit: int = Field(default=8, ge=1, le=64)
    handler_default_timeout_s: float = Field(default=30.0, ge=1)
    backpressure_warn_s: int = Field(default=10, ge=1)


class MqttConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker_host: str = "broker"
    broker_port: int = Field(default=1883, ge=1, le=65535)
    keepalive_s: int = Field(default=30, ge=5)
    max_connect_attempts: int = Field(default=10, ge=1)
    reconnect_give_up_s: int = Field(default=120, ge=10)
    # Literal env-var NAME to consult later (not a ${ENV:...} pattern).
    password_env: str | None = None


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warn", "error"] = "info"
    structured: bool = True
    include_envelope_ids: bool = True


class RegionConfig(BaseModel):
    """Top-level region config — spec §F.2 / §F.5."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{2,30}$")
    role: str = Field(..., min_length=10, max_length=500)
    llm: LlmConfig
    capabilities: CapabilityProfile
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    dispatch: DispatchConfig = Field(default_factory=DispatchConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Module-level resources: schema validator + defaults loaded once at import.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_SCHEMA_PATH = _HERE / "config_schema.json"
_DEFAULTS_PATH = _HERE / "defaults.yaml"

_VALIDATOR = Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
)


def _load_defaults() -> dict[str, Any]:
    """Read ``defaults.yaml`` fresh on each call so tests can monkey-patch."""
    yaml = YAML(typ="safe")
    with _DEFAULTS_PATH.open("r", encoding="utf-8") as f:
        loaded = yaml.load(f)
    return dict(loaded) if loaded is not None else {}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _deep_merge(defaults: dict[str, Any], region: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge — region values override defaults at leaf level.

    Lists and scalars do NOT merge. Only dict values are recursed into.
    Returns a new dict; inputs are not mutated.
    """
    merged: dict[str, Any] = dict(defaults)
    for key, region_val in region.items():
        default_val = merged.get(key)
        if isinstance(default_val, dict) and isinstance(region_val, dict):
            merged[key] = _deep_merge(default_val, region_val)
        else:
            merged[key] = region_val
    return merged


_ENV_PATTERN = re.compile(r"^\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}$")


def _interp_env(value: Any) -> Any:
    """Replace ``${ENV:VAR}`` scalar strings with ``os.environ['VAR']``.

    Recurses into dicts and lists. Only applies when a string matches the
    full pattern — partial-string substitution is intentionally out of scope
    for v0. Non-string scalars pass through unchanged. Missing env vars raise
    :class:`ConfigError`.
    """
    if isinstance(value, dict):
        return {k: _interp_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interp_env(v) for v in value]
    if isinstance(value, str):
        match = _ENV_PATTERN.match(value)
        if match is None:
            return value
        var_name = match.group(1)
        if var_name not in os.environ:
            raise ConfigError(f"required env var {var_name} not set")
        return os.environ[var_name]
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path) -> RegionConfig:
    """Load, merge, validate, interpolate, and typecheck a region config file.

    See the module docstring for the pipeline; see spec §F.5 for the contract.
    All failure modes surface as :class:`ConfigError` — callers need to handle
    only that one exception type.
    """
    path = Path(path)

    # 1. Read YAML
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"failed to read config file {path}: {exc}") from exc

    yaml = YAML(typ="safe")
    try:
        data = yaml.load(raw_text)
    except YAMLError as exc:
        raise ConfigError(f"malformed YAML in {path}: {exc}") from exc

    if data is None:
        raise ConfigError(f"config file is empty: {path}")
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path}: config must be a YAML mapping at the top level; "
            f"got {type(data).__name__}"
        )

    # 2. Deep-merge over defaults
    defaults = _load_defaults()
    merged = _deep_merge(defaults, data)

    # 3. JSON-schema validate (spec §F.2)
    try:
        _VALIDATOR.validate(merged)
    except JsonSchemaValidationError as exc:
        # exc.absolute_path is a deque of field names leading to the bad value.
        # Empty deque → top-level issue; surface as "<root>".
        path_parts = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ConfigError(
            f"{path}: config schema violation at {path_parts}: {exc.message}"
        ) from exc

    # 4. Env interpolation
    try:
        merged = _interp_env(merged)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc

    # 5. Construct typed object
    try:
        return RegionConfig(**merged)
    except ValidationError as exc:
        raise ConfigError(f"{path}: config model violation: {exc}") from exc
