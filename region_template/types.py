"""Shared type vocabulary for the Hive region runtime.

Exports three names consumed by all other region_template modules:

- ``LifecyclePhase`` — FSM phase enum (spec §A.4.1)
- ``CapabilityProfile`` — Pydantic model for the capabilities block (spec §F.2)
- ``HandlerContext`` — frozen dataclass passed to every handler (spec §A.6.2)

Types that refer to not-yet-implemented modules (``LlmAdapter``, ``MemoryStore``,
``SelfModifyTools``) are imported under ``TYPE_CHECKING`` only, so this file is
importable standalone. The concrete classes land in Tasks 3.8, 3.9, 3.11.
"""
from __future__ import annotations

import dataclasses
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from region_template.llm_adapter import LlmAdapter
    from region_template.memory import MemoryStore
    from region_template.self_modify import SelfModifyTools


# ---------------------------------------------------------------------------
# LifecyclePhase — §A.4.1
# ---------------------------------------------------------------------------

class LifecyclePhase(str, Enum):
    """Four-phase FSM for the region runtime.

    Restart is modelled via SHUTDOWN with exit-code 0 (§A.4.4); there is no
    RESTARTING member.
    """

    BOOTSTRAP = "bootstrap"
    WAKE = "wake"
    SLEEP = "sleep"
    SHUTDOWN = "shutdown"


# ---------------------------------------------------------------------------
# CapabilityProfile — §F.2 capabilities object
# ---------------------------------------------------------------------------

class CapabilityProfile(BaseModel):
    """Pydantic v2 model for the ``capabilities`` block in config.yaml.

    Required fields mirror the JSON Schema ``required`` array (§F.2 line 3383).
    Optional fields default to the §F.2 intent (off / empty list).
    ``extra="forbid"`` matches ``additionalProperties: false`` in the schema.
    """

    model_config = ConfigDict(extra="forbid")

    # Required
    self_modify: bool
    tool_use: Literal["none", "basic", "advanced"]
    vision: bool
    audio: bool

    # Optional with defaults
    stream: bool = False
    can_spawn: bool = False
    modalities: list[Literal["text", "vision", "audio", "motor", "smell", "haptic"]] = Field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# HandlerContext — §A.6.2
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class HandlerContext:
    """Immutable context object passed as the second argument to every handler.

    ``tools`` is always present; individual tool calls fail at runtime if the
    required capability is missing or the phase is wrong (§A.6.2, §A.7).
    """

    region_name: str
    phase: LifecyclePhase
    publish: Callable[..., Awaitable[None]]
    llm: "LlmAdapter"
    memory: "MemoryStore"
    tools: "SelfModifyTools"  # present but gated by capability + phase
    request_sleep: Callable[[str], None]
    log: structlog.BoundLogger
