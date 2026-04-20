"""Tests for region_template.types — spec §A.4.1, §A.6.2, §F.2.

Covers:
  1. Import smoke: LifecyclePhase, CapabilityProfile, HandlerContext importable.
  2. LifecyclePhase shape: exactly 4 members with lowercase str values; str-Enum; no RESTARTING.
  3. CapabilityProfile happy-path construction and default values.
  4. CapabilityProfile validation: missing required field, bad enum literal, extra field, modalities.
  5. HandlerContext shape: is_dataclass; field names; frozen (FrozenInstanceError on mutation).
"""
from __future__ import annotations

import dataclasses

import pytest
import pydantic

from region_template.types import LifecyclePhase, CapabilityProfile, HandlerContext


# ---------------------------------------------------------------------------
# 1. Import smoke test (no explicit assertion — collection failure = fail)
# ---------------------------------------------------------------------------

def test_imports_succeed():
    """All three public names are importable from region_template.types."""
    assert LifecyclePhase is not None
    assert CapabilityProfile is not None
    assert HandlerContext is not None


# ---------------------------------------------------------------------------
# 2. LifecyclePhase shape
# ---------------------------------------------------------------------------

def test_lifecycle_phase_member_names():
    assert {m.name for m in LifecyclePhase} == {"BOOTSTRAP", "WAKE", "SLEEP", "SHUTDOWN"}


def test_lifecycle_phase_values_are_lowercase():
    assert LifecyclePhase.BOOTSTRAP.value == "bootstrap"
    assert LifecyclePhase.WAKE.value == "wake"
    assert LifecyclePhase.SLEEP.value == "sleep"
    assert LifecyclePhase.SHUTDOWN.value == "shutdown"


def test_lifecycle_phase_is_str_enum():
    assert isinstance(LifecyclePhase.WAKE, str)
    assert isinstance(LifecyclePhase.BOOTSTRAP, str)
    assert isinstance(LifecyclePhase.SLEEP, str)
    assert isinstance(LifecyclePhase.SHUTDOWN, str)


def test_lifecycle_phase_no_restarting():
    names = {m.name for m in LifecyclePhase}
    assert "RESTARTING" not in names


# ---------------------------------------------------------------------------
# 3. CapabilityProfile happy-path construction and defaults
# ---------------------------------------------------------------------------

def test_capability_profile_minimal_construction():
    cap = CapabilityProfile(self_modify=False, tool_use="basic", vision=False, audio=False)
    assert cap.self_modify is False
    assert cap.tool_use == "basic"
    assert cap.vision is False
    assert cap.audio is False


def test_capability_profile_optional_defaults():
    cap = CapabilityProfile(self_modify=True, tool_use="none", vision=True, audio=True)
    assert cap.stream is False
    assert cap.can_spawn is False
    assert cap.modalities == []


def test_capability_profile_all_tool_use_literals():
    for value in ("none", "basic", "advanced"):
        cap = CapabilityProfile(self_modify=False, tool_use=value, vision=False, audio=False)
        assert cap.tool_use == value


def test_capability_profile_modalities_valid():
    cap = CapabilityProfile(
        self_modify=False,
        tool_use="none",
        vision=False,
        audio=False,
        modalities=["smell"],
    )
    assert cap.modalities == ["smell"]


def test_capability_profile_all_optional_fields():
    cap = CapabilityProfile(
        self_modify=True,
        tool_use="advanced",
        vision=True,
        audio=True,
        stream=True,
        can_spawn=True,
        modalities=["text", "vision", "audio", "motor", "smell", "haptic"],
    )
    assert cap.stream is True
    assert cap.can_spawn is True
    assert len(cap.modalities) == 6


# ---------------------------------------------------------------------------
# 4. CapabilityProfile validation errors
# ---------------------------------------------------------------------------

def test_capability_profile_missing_required_field_raises():
    with pytest.raises(pydantic.ValidationError):
        # missing 'audio'
        CapabilityProfile(self_modify=False, tool_use="basic", vision=False)


def test_capability_profile_bad_tool_use_raises():
    with pytest.raises(pydantic.ValidationError):
        CapabilityProfile(self_modify=False, tool_use="wizard", vision=False, audio=False)


def test_capability_profile_extra_field_raises():
    with pytest.raises(pydantic.ValidationError):
        CapabilityProfile(
            self_modify=False, tool_use="basic", vision=False, audio=False, telepathy=True
        )


def test_capability_profile_bad_modality_raises():
    with pytest.raises(pydantic.ValidationError):
        CapabilityProfile(
            self_modify=False,
            tool_use="none",
            vision=False,
            audio=False,
            modalities=["sonar"],
        )


def test_capability_profile_smell_is_valid_modality():
    cap = CapabilityProfile(
        self_modify=False,
        tool_use="none",
        vision=False,
        audio=False,
        modalities=["smell"],
    )
    assert "smell" in cap.modalities


# ---------------------------------------------------------------------------
# 5. HandlerContext shape
# ---------------------------------------------------------------------------

def test_handler_context_is_dataclass():
    assert dataclasses.is_dataclass(HandlerContext)


def test_handler_context_field_names():
    field_names = {f.name for f in dataclasses.fields(HandlerContext)}
    assert field_names == {
        "region_name",
        "phase",
        "publish",
        "llm",
        "memory",
        "tools",
        "request_sleep",
        "log",
    }


def test_handler_context_is_frozen():
    """Constructing with dummy stand-ins and attempting mutation raises FrozenInstanceError."""
    dummy = object()

    ctx = HandlerContext(
        region_name="test_region",
        phase=LifecyclePhase.WAKE,
        publish=dummy,
        llm=dummy,
        memory=dummy,
        tools=dummy,
        request_sleep=dummy,
        log=dummy,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.phase = LifecyclePhase.SLEEP  # type: ignore[misc]


def test_handler_context_field_order():
    """Field order matches §A.6.2 exactly: region_name, phase, publish, llm, memory, tools,
    request_sleep, log."""
    expected_order = [
        "region_name", "phase", "publish", "llm", "memory", "tools", "request_sleep", "log"
    ]
    actual_order = [f.name for f in dataclasses.fields(HandlerContext)]
    assert actual_order == expected_order
