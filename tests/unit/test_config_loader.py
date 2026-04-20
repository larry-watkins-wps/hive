"""Tests for region_template.config_loader — spec §F.5.

Covers:
  1. Valid fixture config parses and required fields are present.
  2. Defaults from ``region_template/defaults.yaml`` fill missing optional sections.
  3. Region value wins over default (leaf-level deep merge).
  4. Missing ``llm.provider`` → ConfigError.
  5. ``capabilities.tool_use: "wizard"`` (outside enum) → ConfigError.
  6. Missing required field (``name``) → ConfigError.
  7. Extra field on nested block (additionalProperties: false) → ConfigError.
  8. Wrong ``schema_version`` → ConfigError.
  9. Bad ``name`` pattern (e.g. uppercase) → ConfigError.
 10. ``${ENV:VAR}`` interpolation replaces value; missing env → ConfigError.
 11. ``mqtt.password_env`` is a literal env-var name and is NOT interpolated.
 12. Missing file path → ConfigError.
 13. Malformed YAML → ConfigError.
 14. Capabilities block composes into CapabilityProfile (§F.2 shape).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from region_template import config_loader as _cl_module
from region_template.config_loader import RegionConfig, load_config
from region_template.errors import ConfigError
from region_template.types import CapabilityProfile

# ---------------------------------------------------------------------------
# Helpers + spec-anchored expected constants (§F.6 defaults)
# ---------------------------------------------------------------------------

_YAML = YAML(typ="safe")

# Defaults from defaults.yaml (§F.6) — mirror these here so assertions are
# named, not magic numbers.
_DEFAULT_HEARTBEAT_S = 5
_DEFAULT_SHUTDOWN_TIMEOUT_S = 30
_DEFAULT_MQTT_PORT = 1883
_DEFAULT_STM_MAX_BYTES = 262_144
_DEFAULT_HANDLER_CONCURRENCY = 8
_DEFAULT_PER_CALL_MAX_TOKENS = 2048
_DEFAULT_MAX_ATTEMPTS = 3

# Region-override values used in merge tests
_REGION_HEARTBEAT_S = 10
_REGION_HEARTBEAT_ALT_S = 7
_REGION_TEMPERATURE = 0.1


def _write_fixture(tmp_path: Path, data: dict, name: str = "config.yaml") -> Path:
    """Write ``data`` as YAML to ``tmp_path / name`` and return the path."""
    path = tmp_path / name
    with path.open("w", encoding="utf-8") as f:
        _YAML.dump(data, f)
    return path


def _minimal_valid_config() -> dict:
    """A fully valid minimal region config (all required fields present)."""
    return {
        "schema_version": 1,
        "name": "fixture",
        "role": "A fixture region used only in tests.",
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
        "capabilities": {
            "self_modify": False,
            "tool_use": "basic",
            "vision": False,
            "audio": False,
        },
    }


# ---------------------------------------------------------------------------
# 1–3. Happy path + defaults merge
# ---------------------------------------------------------------------------


def test_load_config_parses_required_fields(tmp_path):
    path = _write_fixture(tmp_path, _minimal_valid_config())
    cfg = load_config(path)

    assert isinstance(cfg, RegionConfig)
    assert cfg.name == "fixture"
    assert cfg.schema_version == 1
    assert cfg.role == "A fixture region used only in tests."
    assert cfg.llm.provider == "openai"
    assert cfg.llm.model == "gpt-4o-mini"


def test_load_config_returns_capability_profile(tmp_path):
    """Capabilities block is composed into a CapabilityProfile."""
    path = _write_fixture(tmp_path, _minimal_valid_config())
    cfg = load_config(path)

    assert isinstance(cfg.capabilities, CapabilityProfile)
    assert cfg.capabilities.self_modify is False
    assert cfg.capabilities.tool_use == "basic"


def test_load_config_defaults_fill_in_missing_optional_sections(tmp_path):
    """Optional sections not specified by the region take §F.6 defaults."""
    path = _write_fixture(tmp_path, _minimal_valid_config())
    cfg = load_config(path)

    # §F.6 defaults
    assert cfg.lifecycle.heartbeat_interval_s == _DEFAULT_HEARTBEAT_S
    assert cfg.lifecycle.shutdown_timeout_s == _DEFAULT_SHUTDOWN_TIMEOUT_S
    assert cfg.mqtt.broker_host == "broker"
    assert cfg.mqtt.broker_port == _DEFAULT_MQTT_PORT
    assert cfg.memory.stm_max_bytes == _DEFAULT_STM_MAX_BYTES
    assert cfg.dispatch.handler_concurrency_limit == _DEFAULT_HANDLER_CONCURRENCY
    assert cfg.logging.level == "info"
    assert cfg.llm.budgets.per_call_max_tokens == _DEFAULT_PER_CALL_MAX_TOKENS
    assert cfg.llm.retry.max_attempts == _DEFAULT_MAX_ATTEMPTS
    assert cfg.llm.caching.strategy == "system"


def test_region_value_wins_over_default(tmp_path):
    """When a nested leaf is specified by the region, it overrides the default."""
    data = _minimal_valid_config()
    data["lifecycle"] = {"heartbeat_interval_s": _REGION_HEARTBEAT_S}
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)

    assert cfg.lifecycle.heartbeat_interval_s == _REGION_HEARTBEAT_S
    # Other lifecycle fields remain at defaults — deep merge, not replace.
    assert cfg.lifecycle.shutdown_timeout_s == _DEFAULT_SHUTDOWN_TIMEOUT_S


def test_region_llm_params_merge_with_defaults(tmp_path):
    """Region llm.params keys merge with default llm.params keys at leaf level."""
    data = _minimal_valid_config()
    data["llm"]["params"] = {"temperature": _REGION_TEMPERATURE}
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)

    # region key wins
    assert cfg.llm.params["temperature"] == _REGION_TEMPERATURE
    # default key preserved
    assert cfg.llm.params["max_tokens"] == _DEFAULT_PER_CALL_MAX_TOKENS


# ---------------------------------------------------------------------------
# 4–9. Validation errors via JSON schema / Pydantic
# ---------------------------------------------------------------------------


def test_missing_llm_provider_raises(tmp_path):
    data = _minimal_valid_config()
    del data["llm"]["provider"]
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)
    # Error should locate the failure at/under the llm block so ops can
    # disambiguate. Don't pin exact wording — assert the field path is present.
    msg = str(exc_info.value)
    assert "llm" in msg


def test_tool_use_outside_enum_raises(tmp_path):
    data = _minimal_valid_config()
    data["capabilities"]["tool_use"] = "wizard"
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)
    # Schema-violation messages must surface the JSON path so operators
    # aren't left grepping the schema.
    msg = str(exc_info.value)
    assert "capabilities.tool_use" in msg


def test_missing_name_raises(tmp_path):
    data = _minimal_valid_config()
    del data["name"]
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


def test_wrong_schema_version_raises(tmp_path):
    data = _minimal_valid_config()
    data["schema_version"] = 2
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


def test_name_with_uppercase_raises(tmp_path):
    data = _minimal_valid_config()
    data["name"] = "Foo"
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


def test_extra_field_on_capabilities_raises(tmp_path):
    """additionalProperties: false on capabilities rejects unknown keys."""
    data = _minimal_valid_config()
    data["capabilities"]["extra_bool"] = True
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


def test_extra_field_on_root_raises(tmp_path):
    """Top-level additionalProperties: false rejects unknown top-level keys."""
    data = _minimal_valid_config()
    data["mystery_block"] = {"x": 1}
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


def test_short_role_raises(tmp_path):
    """role minLength: 10 — a short role string is rejected."""
    data = _minimal_valid_config()
    data["role"] = "x"
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError):
        load_config(path)


# ---------------------------------------------------------------------------
# 10–11. Env interpolation
# ---------------------------------------------------------------------------


def test_env_interpolation_replaces_value(tmp_path, monkeypatch):
    """A scalar string ``${ENV:VAR}`` is replaced with os.environ['VAR']."""
    monkeypatch.setenv("HIVE_TEST_PROVIDER", "anthropic")
    data = _minimal_valid_config()
    data["llm"]["provider"] = "${ENV:HIVE_TEST_PROVIDER}"
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)
    assert cfg.llm.provider == "anthropic"


def test_env_interpolation_missing_env_raises(tmp_path, monkeypatch):
    """Missing env var referenced via ${ENV:VAR} → ConfigError.

    The error should name the missing env var AND include the config file
    path so ops can disambiguate when multiple regions fail at boot.
    """
    monkeypatch.delenv("HIVE_TEST_MISSING", raising=False)
    data = _minimal_valid_config()
    data["llm"]["provider"] = "${ENV:HIVE_TEST_MISSING}"
    path = _write_fixture(tmp_path, data)
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)
    msg = str(exc_info.value)
    assert "HIVE_TEST_MISSING" in msg
    assert str(path) in msg


def test_env_interpolation_nested_dict(tmp_path, monkeypatch):
    """Interpolation recurses into nested dicts."""
    monkeypatch.setenv("HIVE_TEST_HOST", "rabbitmq.local")
    data = _minimal_valid_config()
    data["mqtt"] = {"broker_host": "${ENV:HIVE_TEST_HOST}"}
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)
    assert cfg.mqtt.broker_host == "rabbitmq.local"


def test_password_env_is_not_interpolated(tmp_path, monkeypatch):
    """
    mqtt.password_env holds the *name* of an env var to consult later —
    it is a literal string, not a ${ENV:VAR} pattern. It must NOT be
    interpolated at load time.
    """
    monkeypatch.setenv("MY_MQTT_PASSWORD", "should-not-be-resolved")
    data = _minimal_valid_config()
    data["mqtt"] = {"password_env": "MY_MQTT_PASSWORD"}
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)
    # password_env is preserved as the literal env-var *name*.
    assert cfg.mqtt.password_env == "MY_MQTT_PASSWORD"


def test_env_interpolation_pattern_anywhere_string_only(tmp_path, monkeypatch):
    """Non-string values (ints, bools) are left alone by interpolation."""
    data = _minimal_valid_config()
    data["lifecycle"] = {"heartbeat_interval_s": _REGION_HEARTBEAT_ALT_S}
    path = _write_fixture(tmp_path, data)
    cfg = load_config(path)
    assert cfg.lifecycle.heartbeat_interval_s == _REGION_HEARTBEAT_ALT_S


# ---------------------------------------------------------------------------
# 12–13. File errors
# ---------------------------------------------------------------------------


def test_missing_file_raises(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigError):
        load_config(missing)


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("key: value\n  bad_indent: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


# ---------------------------------------------------------------------------
# 14. Defaults file exists and is usable
# ---------------------------------------------------------------------------


def test_defaults_file_shipped():
    """region_template/defaults.yaml must exist next to the loader."""
    defaults = Path(_cl_module.__file__).parent / "defaults.yaml"
    assert defaults.exists(), f"defaults.yaml missing at {defaults}"


def test_schema_file_shipped():
    """region_template/config_schema.json must exist next to the loader."""
    schema = Path(_cl_module.__file__).parent / "config_schema.json"
    assert schema.exists(), f"config_schema.json missing at {schema}"
