"""Tests for region_template.capability — spec §A.7.8.

Covers the two method decorators that gate tool calls on capabilities declared
in config.yaml (``@requires_capability``) and on the runtime's current FSM
phase (``@sleep_only``). Both decorators are designed to be applied to methods
of a class (e.g. ``SelfModifyTools``) that exposes:

  - ``self._caps`` — a ``dict[str, bool]`` mirror of CapabilityProfile
  - ``self._runtime`` — an object with a ``.phase`` attribute of type
    ``LifecyclePhase``

Tests:
  1. ``@requires_capability`` raises ``CapabilityDenied`` when the capability
     is missing from ``_caps``.
  2. ``@requires_capability`` raises ``CapabilityDenied`` when the capability
     is present but set to False.
  3. ``@requires_capability`` passes through when the capability is True.
  4. ``@sleep_only`` raises ``PhaseViolation`` when ``_runtime.phase`` is WAKE.
  5. ``@sleep_only`` raises ``PhaseViolation`` for BOOTSTRAP and SHUTDOWN too.
  6. ``@sleep_only`` passes through when ``_runtime.phase`` is SLEEP.
  7. Stacked decorators: happy path returns the wrapped method's value.
  8. Stacked decorators: capability missing raises ``CapabilityDenied``
     (checked before phase — capability decorator is on top).
  9. Stacked decorators: capability present + wrong phase raises
     ``PhaseViolation``.
 10. ``@requires_capability("a", "b")`` with multiple caps raises
     ``CapabilityDenied`` on the first missing one (order preserved).
 11. ``@wraps`` preserves ``__name__`` on the wrapped method.
 12. ``CapabilityDenied`` carries the missing capability name as its message.
 13. ``PhaseViolation`` carries the current phase as its message.
 14. Decorated methods forward positional and keyword args.
"""
from __future__ import annotations

import types as _pytypes

import pytest

from region_template.capability import requires_capability, sleep_only
from region_template.errors import CapabilityDenied, PhaseViolation
from region_template.types import LifecyclePhase

# ---------------------------------------------------------------------------
# Test helper class — mirrors the SelfModifyTools shape from spec §A.7.8
# ---------------------------------------------------------------------------


class _Owner:
    """Minimal stand-in for ``SelfModifyTools``.

    Exposes ``_caps`` and ``_runtime`` exactly like the spec's SelfModifyTools
    so the decorators can be exercised in isolation.
    """

    def __init__(self, caps: dict[str, bool], phase: LifecyclePhase) -> None:
        self._caps = caps
        self._runtime = _pytypes.SimpleNamespace(phase=phase)

    @requires_capability("self_modify")
    async def cap_guarded(self) -> str:
        return "ok"

    @sleep_only
    async def phase_guarded(self) -> str:
        return "ok"

    @requires_capability("self_modify")
    @sleep_only
    async def both(self, x: str, *, y: str = "") -> str:
        return x + y

    @requires_capability("a", "b")
    async def multi_cap(self) -> str:
        return "ok"


# ---------------------------------------------------------------------------
# 1–3. requires_capability
# ---------------------------------------------------------------------------


async def test_requires_capability_raises_when_missing():
    """Capability absent from _caps dict → CapabilityDenied."""
    owner = _Owner(caps={}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied):
        await owner.cap_guarded()


async def test_requires_capability_raises_when_false():
    """Capability present but False → CapabilityDenied."""
    owner = _Owner(caps={"self_modify": False}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied):
        await owner.cap_guarded()


async def test_requires_capability_passes_when_true():
    """Capability present and True → method runs and returns its value."""
    owner = _Owner(caps={"self_modify": True}, phase=LifecyclePhase.SLEEP)
    assert await owner.cap_guarded() == "ok"


# ---------------------------------------------------------------------------
# 4–6. sleep_only
# ---------------------------------------------------------------------------


async def test_sleep_only_raises_during_wake():
    owner = _Owner(caps={}, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await owner.phase_guarded()


@pytest.mark.parametrize(
    "phase",
    [LifecyclePhase.WAKE, LifecyclePhase.BOOTSTRAP, LifecyclePhase.SHUTDOWN],
    ids=["wake", "bootstrap", "shutdown"],
)
async def test_sleep_only_raises_in_non_sleep_phases(phase):
    owner = _Owner(caps={}, phase=phase)
    with pytest.raises(PhaseViolation):
        await owner.phase_guarded()


async def test_sleep_only_passes_during_sleep():
    owner = _Owner(caps={}, phase=LifecyclePhase.SLEEP)
    assert await owner.phase_guarded() == "ok"


# ---------------------------------------------------------------------------
# 7–9. Stacked decorators
# ---------------------------------------------------------------------------


async def test_stacked_happy_path():
    owner = _Owner(caps={"self_modify": True}, phase=LifecyclePhase.SLEEP)
    assert await owner.both("a", y="b") == "ab"


async def test_stacked_missing_capability_raises_capability_denied():
    """Capability decorator is outermost (on top) — it checks first."""
    owner = _Owner(caps={}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied):
        await owner.both("x")


async def test_stacked_wrong_phase_raises_phase_violation():
    """Capability present, but phase wrong → phase decorator rejects."""
    owner = _Owner(caps={"self_modify": True}, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await owner.both("x")


# ---------------------------------------------------------------------------
# 10. Multiple capabilities — first missing one wins
# ---------------------------------------------------------------------------


async def test_multiple_capabilities_first_missing_wins():
    """``requires_capability("a", "b")`` raises on ``a`` when ``a`` is missing."""
    owner = _Owner(caps={"a": False, "b": True}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied) as exc_info:
        await owner.multi_cap()
    assert "a" in str(exc_info.value)


async def test_multiple_capabilities_second_missing_reported():
    """First cap present, second missing → raises on the second."""
    owner = _Owner(caps={"a": True, "b": False}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied) as exc_info:
        await owner.multi_cap()
    assert "b" in str(exc_info.value)


async def test_multiple_capabilities_all_present():
    owner = _Owner(caps={"a": True, "b": True}, phase=LifecyclePhase.SLEEP)
    assert await owner.multi_cap() == "ok"


# ---------------------------------------------------------------------------
# 11. @wraps preservation
# ---------------------------------------------------------------------------


def test_wraps_preserves_name_requires_capability():
    assert _Owner.cap_guarded.__name__ == "cap_guarded"


def test_wraps_preserves_name_sleep_only():
    assert _Owner.phase_guarded.__name__ == "phase_guarded"


def test_wraps_preserves_name_stacked():
    assert _Owner.both.__name__ == "both"


# ---------------------------------------------------------------------------
# 12–13. Error payloads
# ---------------------------------------------------------------------------


async def test_capability_denied_carries_capability_name():
    owner = _Owner(caps={}, phase=LifecyclePhase.SLEEP)
    with pytest.raises(CapabilityDenied) as exc_info:
        await owner.cap_guarded()
    assert str(exc_info.value) == "self_modify"


async def test_phase_violation_carries_current_phase():
    """PhaseViolation's message is the string form of the offending phase.

    ``LifecyclePhase`` is a ``StrEnum``, so ``str(phase)`` yields the member
    value (``"wake"``), not ``"LifecyclePhase.WAKE"``.
    """
    owner = _Owner(caps={}, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation) as exc_info:
        await owner.phase_guarded()
    assert str(exc_info.value) == "wake"


# ---------------------------------------------------------------------------
# 14. Argument forwarding
# ---------------------------------------------------------------------------


async def test_args_and_kwargs_forwarded_through_decorators():
    owner = _Owner(caps={"self_modify": True}, phase=LifecyclePhase.SLEEP)
    # Positional
    assert await owner.both("alpha") == "alpha"
    # Positional + keyword
    assert await owner.both("alpha", y="beta") == "alphabeta"
