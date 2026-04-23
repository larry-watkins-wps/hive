"""Capability + phase gate decorators — spec §A.7.8.

Two method decorators that guard tool calls on ``SelfModifyTools`` (and any
other owner class that follows the same convention):

- ``@requires_capability(*caps)`` — raises :class:`CapabilityDenied` if any of
  ``caps`` is missing from (or set to False in) ``self._caps``.
- ``@sleep_only`` — raises :class:`PhaseViolation` unless
  ``self._runtime.phase`` is :attr:`LifecyclePhase.SLEEP`.

Both decorators are intended to be applied to ``async`` methods of a class
that exposes:

- ``self._caps`` — a ``dict[str, bool]`` mirror of ``CapabilityProfile``
- ``self._runtime`` — an object with a ``.phase`` attribute of type
  ``LifecyclePhase``

When stacked (``@requires_capability`` outermost, ``@sleep_only`` inner),
the capability check runs first; only if it passes does the phase check run.
This matches the spec's usage pattern on :class:`SelfModifyTools`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from region_template.errors import CapabilityDenied, PhaseViolation
from region_template.types import LifecyclePhase

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def requires_capability(*caps: str) -> Callable[[F], F]:
    """Gate an async method on one or more declared capabilities.

    Reads ``self._caps`` (a ``dict[str, bool]``) and raises
    :class:`CapabilityDenied` with the first missing capability name if any
    of ``caps`` is absent or falsy.
    """

    def dec(fn: F) -> F:
        @wraps(fn)
        async def wrapper(self: Any, *a: Any, **kw: Any) -> Any:
            for c in caps:
                if not self._caps.get(c):
                    raise CapabilityDenied(c)
            return await fn(self, *a, **kw)

        return wrapper  # type: ignore[return-value]

    return dec


def sleep_only(fn: F) -> F:
    """Gate an async method on ``LifecyclePhase.SLEEP``.

    Reads ``self._runtime.phase`` and raises :class:`PhaseViolation` carrying
    the current phase if it is not ``SLEEP``.
    """

    @wraps(fn)
    async def wrapper(self: Any, *a: Any, **kw: Any) -> Any:
        if self._runtime.phase != LifecyclePhase.SLEEP:
            raise PhaseViolation(self._runtime.phase)
        return await fn(self, *a, **kw)

    return wrapper  # type: ignore[return-value]
