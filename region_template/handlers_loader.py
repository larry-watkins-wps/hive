"""Handler discovery for the Hive region runtime — spec §A.6.1, §A.6.3, §A.6.4.

A region's handlers live as individual ``.py`` files directly under the
region's ``handlers/`` directory. Each file declares module-level constants
(:data:`SUBSCRIPTIONS`, optional :data:`TIMEOUT_S` / :data:`QOS` /
:data:`ON_HEARTBEAT` / :data:`REQUIRES_CAPABILITY`) and exports a coroutine::

    async def handle(envelope: Envelope, ctx: HandlerContext) -> None: ...

The runtime does NOT use decorators — matching is done by comparing inbound
envelopes against each handler's ``SUBSCRIPTIONS`` list.

:func:`discover` imports every direct-child ``.py`` file (except
``__init__.py``), validates the contract, and returns a filename-sorted
``list[HandlerModule]``. Per-envelope dispatch order (exact-match first,
wildcard second) is applied by :func:`match_handlers_for_topic`, which the
dispatch loop in Task 3.15 will call for each inbound topic.

Spec behaviour implemented here:

- Only direct-child ``.py`` files; no recursion (§A.6.3).
- Files lacking ``SUBSCRIPTIONS`` (or with an empty / non-list value) are
  skipped with a WARN log (§A.6.3).
- Files that fail to import, or whose ``handle`` is missing / not an
  ``async def``, are skipped with an ERROR log — the region still boots
  (§A.6.3).
- Duplicate *exact* topic filters across two files raise
  :class:`~region_template.errors.ConfigError` (bootstrap failure,
  §A.6.3). Overlapping *wildcards* are not a conflict.
- Hot-reload (``watchfiles``) is explicitly **out of scope** for v0
  (spec §K.3 — dev-mode only).
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import structlog

from region_template.errors import ConfigError
from region_template.types import HandlerContext
from shared.message_envelope import Envelope
from shared.topics import topic_matches

__all__ = [
    "HandlerModule",
    "discover",
    "match_handlers_for_topic",
]

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Default constant values — spec §A.6.1 table
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S: float = 30.0
_DEFAULT_QOS: int = 1
_DEFAULT_ON_HEARTBEAT: bool = False
_DEFAULT_REQUIRES_CAPABILITY: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Public value type — one loaded handler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandlerModule:
    """One loaded handler — the unit the runtime dispatches against.

    Spec: §A.6.1 (contract), §A.6.3 (discovery), §A.6.4 (dispatch order).

    Attributes:
        name: Filename stem, e.g. ``"on_audio"``.
        path: Absolute path to the source ``.py`` file.
        subscriptions: Frozen copy of the file's ``SUBSCRIPTIONS`` list.
        timeout_s: Per-invocation hard timeout (default 30.0).
        qos: MQTT QoS level to subscribe at (default 1).
        on_heartbeat: When True, runtime also invokes on each heartbeat tick.
        requires_capability: Capabilities that must appear in the region's
            config for this handler to load (default empty).
        handle: The ``async def handle`` coroutine from the module.
    """

    name: str
    path: Path
    subscriptions: tuple[str, ...]
    timeout_s: float
    qos: int
    on_heartbeat: bool
    requires_capability: tuple[str, ...]
    handle: Callable[[Envelope, HandlerContext], Awaitable[None]]

    @property
    def has_wildcard(self) -> bool:
        """True if any subscription contains MQTT wildcards (``+`` or ``#``)."""
        return any("+" in s or "#" in s for s in self.subscriptions)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _module_name_for(path: Path) -> str:
    """Build a sys.modules key that won't collide across regions.

    Using a hash of the absolute path makes the same stem in two different
    ``handlers/`` dirs land under distinct ``sys.modules`` entries.
    """
    # id() of the spec isn't stable pre-creation; hash the resolved path.
    digest = abs(hash(str(path.resolve())))
    return f"_hive_handler_{path.stem}_{digest:x}"


def _validate_subscriptions(
    raw: object, *, path: Path
) -> tuple[str, ...] | None:
    """Return a frozen tuple of subscription strings, or None if invalid.

    Callers log at WARN when None is returned; the file is then skipped.
    """
    if raw is None:
        log.warning(
            "handler_missing_SUBSCRIPTIONS",
            path=str(path),
        )
        return None
    if not isinstance(raw, list) or not raw:
        log.warning(
            "handler_SUBSCRIPTIONS_empty_or_not_list",
            path=str(path),
            got_type=type(raw).__name__,
        )
        return None
    if not all(isinstance(s, str) and s for s in raw):
        log.warning(
            "handler_SUBSCRIPTIONS_contains_non_string",
            path=str(path),
        )
        return None
    return tuple(raw)


def _normalize_requires_capability(raw: object) -> tuple[str, ...]:
    """Normalize REQUIRES_CAPABILITY to a tuple[str, ...].

    Spec §A.6.1 table declares ``list[str]`` with default ``[]``. The plan
    prose drafts it as ``str`` — spec wins. We accept a bare string as a
    one-element list for ergonomics.
    """
    if raw is None:
        return _DEFAULT_REQUIRES_CAPABILITY
    if isinstance(raw, str):
        return (raw,) if raw else _DEFAULT_REQUIRES_CAPABILITY
    if isinstance(raw, (list, tuple)):
        return tuple(str(x) for x in raw if x)
    return _DEFAULT_REQUIRES_CAPABILITY


def _import_module_file(path: Path) -> object | None:
    """Dynamically import ``path`` and return the module object, or None on failure.

    Any import failure (bad spec, syntax error, runtime error at top level)
    is logged at ERROR and None is returned. This is the plugin boundary —
    per spec §A.6.3 a region must still boot when one handler fails to import.
    """
    module_name = _module_name_for(path)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
    except (OSError, ValueError) as exc:
        log.error("handler_spec_failed", path=str(path), error=str(exc))
        return None

    if spec is None or spec.loader is None:
        log.error("handler_spec_null", path=str(path))
        return None

    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so relative-import / type-annotation lookups work.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — plugin boundary; spec §A.6.3
        log.error(
            "handler_import_failed",
            path=str(path),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        sys.modules.pop(module_name, None)
        return None
    return module


def _extract_handle(module: object, *, path: Path) -> (
    Callable[[Envelope, HandlerContext], Awaitable[None]] | None
):
    """Return the module's ``handle`` coroutine, or None on contract failure."""
    fn = getattr(module, "handle", None)
    if fn is None:
        log.error("handler_missing_handle", path=str(path))
        return None
    if not inspect.iscoroutinefunction(fn):
        log.error(
            "handler_handle_not_async",
            path=str(path),
            got_type=type(fn).__name__,
        )
        return None
    return fn


def _load_one(path: Path) -> HandlerModule | None:
    """Import a single handler file and return a HandlerModule on success.

    Returns None on any failure (missing constant, bad signature, import
    error); the failure is logged at WARN or ERROR depending on its class.
    """
    module = _import_module_file(path)
    if module is None:
        return None

    subscriptions = _validate_subscriptions(
        getattr(module, "SUBSCRIPTIONS", None), path=path
    )
    if subscriptions is None:
        return None

    fn = _extract_handle(module, path=path)
    if fn is None:
        return None

    # --- Read optional constants ------------------------------------------
    timeout_raw = getattr(module, "TIMEOUT_S", _DEFAULT_TIMEOUT_S)
    try:
        timeout_s = float(timeout_raw)
    except (TypeError, ValueError):
        log.warning(
            "handler_TIMEOUT_S_invalid_using_default",
            path=str(path),
            got=repr(timeout_raw),
        )
        timeout_s = _DEFAULT_TIMEOUT_S

    qos_raw = getattr(module, "QOS", _DEFAULT_QOS)
    qos = qos_raw if isinstance(qos_raw, int) and qos_raw in (0, 1, 2) else _DEFAULT_QOS
    if qos is not qos_raw:
        log.warning(
            "handler_QOS_invalid_using_default",
            path=str(path),
            got=repr(qos_raw),
        )

    on_heartbeat_raw = getattr(module, "ON_HEARTBEAT", _DEFAULT_ON_HEARTBEAT)
    on_heartbeat = bool(on_heartbeat_raw)

    requires_capability = _normalize_requires_capability(
        getattr(module, "REQUIRES_CAPABILITY", None)
    )

    return HandlerModule(
        name=path.stem,
        path=path,
        subscriptions=subscriptions,
        timeout_s=timeout_s,
        qos=qos,
        on_heartbeat=on_heartbeat,
        requires_capability=requires_capability,
        handle=fn,
    )


def _check_duplicate_exact_topics(handlers: list[HandlerModule]) -> None:
    """Raise ConfigError if two files declare the same EXACT topic filter.

    Wildcard overlaps are allowed (spec §A.6.3: "duplicate topic→handler
    mappings cause BOOTSTRAP to fail" — interpreted as exact topic collisions;
    wildcards are fanout, not conflict).
    """
    exact_owner: dict[str, str] = {}
    for h in handlers:
        for filter_ in h.subscriptions:
            if "+" in filter_ or "#" in filter_:
                continue
            prior = exact_owner.get(filter_)
            if prior is not None and prior != h.name:
                raise ConfigError(
                    f"duplicate handler for topic {filter_}: "
                    f"{prior} and {h.name}"
                )
            exact_owner[filter_] = h.name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover(handlers_dir: Path) -> list[HandlerModule]:
    """Discover every valid handler under ``handlers_dir``.

    Imports every ``.py`` file directly under ``handlers_dir`` that isn't
    ``__init__.py``, validates the spec §A.6.1 contract, and returns a
    deterministic filename-sorted ``list[HandlerModule]``.

    Per §A.6.3:
    - Only direct-child ``.py`` files; no recursion.
    - Files without SUBSCRIPTIONS: WARN, skipped.
    - Files that fail to import or whose handle isn't ``async def``: ERROR,
      skipped. A region with zero valid handlers is legal.
    - Duplicate exact topic filters across files:
      :class:`~region_template.errors.ConfigError` (bootstrap failure).

    Returns:
        Filename-sorted list of :class:`HandlerModule`. Exact-vs-wildcard
        dispatch ordering is applied per-topic by
        :func:`match_handlers_for_topic`.
    """
    handlers_dir = Path(handlers_dir)
    if not handlers_dir.is_dir():
        # Missing dir is legal — a starter region may have no handlers yet.
        return []

    candidates = sorted(
        p for p in handlers_dir.iterdir()
        if p.is_file() and p.suffix == ".py" and p.name != "__init__.py"
    )

    handlers: list[HandlerModule] = []
    for path in candidates:
        mod = _load_one(path)
        if mod is not None:
            handlers.append(mod)

    _check_duplicate_exact_topics(handlers)
    return handlers


def match_handlers_for_topic(
    handlers: list[HandlerModule], topic: str
) -> list[HandlerModule]:
    """Return the subset of ``handlers`` that match ``topic``, in dispatch order.

    Per spec §A.6.4: exact-match handlers run first, wildcard handlers run
    second. Ties within each tier are broken by filename (alphabetical).

    A handler's "tier for this topic" is determined by the specific filter
    that matches: if any of its subscriptions is exactly ``topic``, it lands
    in the exact tier; otherwise (its match is via ``+`` or ``#``), it lands
    in the wildcard tier.
    """
    exact_tier: list[HandlerModule] = []
    wildcard_tier: list[HandlerModule] = []
    for h in handlers:
        matched_exact = False
        matched_wildcard = False
        for filter_ in h.subscriptions:
            if filter_ == topic:
                matched_exact = True
                break
            if topic_matches(filter_, topic):
                matched_wildcard = True
        if matched_exact:
            exact_tier.append(h)
        elif matched_wildcard:
            wildcard_tier.append(h)

    # Inputs already come filename-sorted from discover(), but sort defensively
    # in case a caller hand-assembles the list.
    exact_tier.sort(key=lambda m: m.name)
    wildcard_tier.sort(key=lambda m: m.name)
    return exact_tier + wildcard_tier
