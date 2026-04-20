"""Tests for region_template.errors — spec §A.9.

Covers:
  1. Import smoke: HiveError + all 9 subclasses importable.
  2. HiveError is a subclass of Exception.
  3. Subclass checks: all 9 subclasses are subclasses of HiveError.
  4. ConnectionError does NOT subclass the stdlib builtin ConnectionError.
  5. LlmError.retryable attribute: default False, can be set True.
  6. Negative assertions: MemoryError, MqttError, SelfModifyError absent from module.
  7. Module surface: all names accessible as module attributes.
  8. Instantiation: each class can be constructed with a message argument.
"""
from __future__ import annotations

import builtins

import pytest

# region_template imports:
#   - `errors` module alias: lets us do `errors.X` without shadowing stdlib names.
#   - `ConnectionError as HiveConnectionError`: avoids shadowing builtins.ConnectionError
#     in this file; any bare `ConnectionError` reference would silently resolve to the Hive
#     class, making stdlib-comparison tests unreliable.
from region_template import errors
from region_template.errors import (
    CapabilityDenied,
    ConfigError,
    GitError,
    HandlerError,
    HiveError,
    LlmError,
    PhaseViolation,
    SandboxEscape,
    StmOverflow,
)
from region_template.errors import (
    ConnectionError as HiveConnectionError,
)

# ---------------------------------------------------------------------------
# 1. Import smoke (collection failure = test fail — no explicit assertion needed)
# ---------------------------------------------------------------------------

def test_imports_succeed():
    """All public error names importable from region_template.errors."""
    assert HiveError is not None
    assert ConfigError is not None
    assert HiveConnectionError is not None
    assert CapabilityDenied is not None
    assert PhaseViolation is not None
    assert HandlerError is not None
    assert SandboxEscape is not None
    assert LlmError is not None
    assert GitError is not None
    assert StmOverflow is not None


# ---------------------------------------------------------------------------
# 2. HiveError is the base
# ---------------------------------------------------------------------------

def test_hive_error_is_exception_subclass():
    assert issubclass(HiveError, Exception)


# ---------------------------------------------------------------------------
# 3. All 9 subclasses are subclasses of HiveError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls",
    [
        ConfigError,
        HiveConnectionError,
        CapabilityDenied,
        PhaseViolation,
        HandlerError,
        SandboxEscape,
        LlmError,
        GitError,
        StmOverflow,
    ],
    ids=[
        "ConfigError",
        "ConnectionError",
        "CapabilityDenied",
        "PhaseViolation",
        "HandlerError",
        "SandboxEscape",
        "LlmError",
        "GitError",
        "StmOverflow",
    ],
)
def test_subclass_of_hive_error(cls):
    assert issubclass(cls, HiveError)


# ---------------------------------------------------------------------------
# 4. Hive's ConnectionError does NOT subclass the stdlib builtin
# ---------------------------------------------------------------------------

def test_hive_connection_error_is_not_stdlib_connection_error():
    """Spec intentionally shadows the builtin — but it must NOT inherit from it.

    If it did inherit, catching builtins.ConnectionError would accidentally catch
    Hive's version, masking the distinction documented in §A.9.
    """
    stdlib_ce = builtins.ConnectionError
    assert not issubclass(HiveConnectionError, stdlib_ce)


def test_hive_connection_error_differs_from_stdlib():
    """Hive's ConnectionError is a distinct class from the stdlib one."""
    assert HiveConnectionError is not builtins.ConnectionError


# ---------------------------------------------------------------------------
# 5. LlmError.retryable attribute
# ---------------------------------------------------------------------------

def test_llm_error_retryable_defaults_false():
    err = LlmError("bad request")
    assert err.retryable is False


def test_llm_error_retryable_can_be_set_true():
    err = LlmError("rate limited", retryable=True)
    assert err.retryable is True


def test_llm_error_retryable_is_bool():
    """Type-ish guard: the attribute is a plain bool, not truthy-arbitrary."""
    assert type(LlmError("x").retryable) is bool
    assert type(LlmError("x", retryable=True).retryable) is bool


# ---------------------------------------------------------------------------
# 6. Negative assertions — spec-excluded names must not exist in the module
# ---------------------------------------------------------------------------

def test_mqtt_error_absent():
    assert not hasattr(errors, "MqttError")


def test_self_modify_error_absent():
    assert not hasattr(errors, "SelfModifyError")


def test_no_custom_memory_error_subclass():
    """stdlib has builtins.MemoryError; verify no Hive subclass of it is defined here.

    We check errors.__dict__ for a locally-defined 'MemoryError' that is a HiveError
    subclass.  The key must either be absent or, if present, NOT be a subclass of HiveError.
    """
    # There must not be any locally-defined MemoryError that is a HiveError subclass.
    local_me = errors.__dict__.get("MemoryError")
    if local_me is not None:
        assert not (isinstance(local_me, type) and issubclass(local_me, HiveError))


# ---------------------------------------------------------------------------
# 7. Module surface — all 10 names accessible as attributes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "HiveError",
        "ConfigError",
        "ConnectionError",
        "CapabilityDenied",
        "PhaseViolation",
        "HandlerError",
        "SandboxEscape",
        "LlmError",
        "GitError",
        "StmOverflow",
    ],
)
def test_module_attribute_accessible(name: str):
    assert hasattr(errors, name)


# ---------------------------------------------------------------------------
# 8. Instantiation: each class can be constructed with a message argument
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls",
    [
        HiveError,
        ConfigError,
        HiveConnectionError,
        CapabilityDenied,
        PhaseViolation,
        HandlerError,
        SandboxEscape,
        LlmError,
        GitError,
        StmOverflow,
    ],
    ids=[
        "HiveError",
        "ConfigError",
        "ConnectionError",
        "CapabilityDenied",
        "PhaseViolation",
        "HandlerError",
        "SandboxEscape",
        "LlmError",
        "GitError",
        "StmOverflow",
    ],
)
def test_instantiation_with_message(cls):
    err = cls("test message")
    assert str(err) == "test message"
