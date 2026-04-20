"""Logging configuration for Hive region runtime — spec §H.1.

Sets up structlog with a JSON-line processor chain and routes stdlib
``logging`` through the same pipeline via ``ProcessorFormatter`` so
third-party libraries (httpx, paho-mqtt, …) appear as JSON, not plain text.

Routes stdlib ``logging`` output through the same structlog processor chain
so third-party library output (httpx, paho-mqtt, etc.) appears as JSON.

Usage::

    from region_template.logging_setup import configure_logging
    configure_logging(region_name="prefrontal_cortex", level="info")

After this call every module obtains a logger with::

    import structlog
    log = structlog.get_logger(__name__)
"""

from __future__ import annotations

import logging
import os
import sys

import structlog
import structlog.contextvars
import structlog.stdlib

# ---------------------------------------------------------------------------
# TODO(§H.1.3): PII redaction processor pending implementation.
# When Task 3.8 (LLM adapter) lands, add a processor here that strips
# Authorization headers and other secrets from the event dict before
# the JSONRenderer runs.
# ---------------------------------------------------------------------------

# Module-level guard — configure_logging is idempotent.
_configured: bool = False

# Map Python/structlog's canonical 'warning' -> spec's 'warn' (§H.1.2).
# structlog's add_log_level processor maps both .warn() and .warning()
# method calls to the string "warning". The spec requires "warn". This
# processor remaps the value AFTER add_log_level has run.
def _remap_warning_to_warn(
    logger: object, method_name: str, event_dict: dict
) -> dict:
    if event_dict.get("level") == "warning":
        event_dict["level"] = "warn"
    return event_dict


def configure_logging(region_name: str, level: str = "info") -> None:
    """Configure structlog + stdlib logging to emit JSON lines to stdout.

    Args:
        region_name: bound into every log line as ``region``.
        level: one of ``"debug"`` | ``"info"`` | ``"warn"`` | ``"error"``
               (case-insensitive).  Defaults to ``"info"``.

    Side effects:
        - Configures structlog's default config globally.
        - Installs a ``ProcessorFormatter`` on the stdlib root handler so
          third-party library output (httpx, paho-mqtt, etc.) is rendered
          through the same processor chain and emitted as JSON.
        - Binds ``region`` and ``pid`` as contextvars.

    Idempotent — safe to call multiple times (useful in tests). Note:
    the ``level`` and ``region_name`` arguments are honored ONLY on the
    first call; subsequent calls are no-ops with respect to configuration.
    To change level at runtime, reset the module's ``_configured`` flag or
    call ``structlog.configure()`` directly.
    """
    global _configured  # noqa: PLW0603

    # Normalise level to uppercase for stdlib logging, lowercase for structlog.
    level_upper = level.upper()
    # Convert 'WARN' to 'WARNING' for stdlib which doesn't know 'WARN'.
    stdlib_level = level_upper if level_upper != "WARN" else "WARNING"
    numeric_level = getattr(logging, stdlib_level, logging.INFO)

    if not _configured:
        # ------------------------------------------------------------------
        # 1. Define shared processors used by BOTH structlog-native loggers
        #    and the stdlib ProcessorFormatter (for third-party libs).
        # ------------------------------------------------------------------
        shared_processors: list = [
            # Pick up correlation_id, phase, and other contextvars.
            structlog.contextvars.merge_contextvars,
            # Add lowercase 'level' key (then remap warning->warn).
            structlog.processors.add_log_level,
            _remap_warning_to_warn,
            # ISO-8601 UTC timestamp under the spec key 'ts'.
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            # Render stack info and exception tracebacks into the event dict.
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        # ------------------------------------------------------------------
        # 2. Install a ProcessorFormatter on the stdlib root handler so that
        #    third-party stdlib logging (httpx, paho-mqtt, etc.) is rendered
        #    through the same chain and emitted as JSON — not plain text.
        # ------------------------------------------------------------------
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(numeric_level)

        # ------------------------------------------------------------------
        # 3. Configure structlog processor chain (§H.1).
        #    Use LoggerFactory so structlog loggers route through stdlib,
        #    which in turn formats via our JSON ProcessorFormatter.
        # ------------------------------------------------------------------
        structlog.configure(
            processors=shared_processors
            + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
            wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        _configured = True

    # ------------------------------------------------------------------
    # 4. Bind per-region context into every subsequent log line.
    #    Done unconditionally so repeated calls update the bound values.
    # ------------------------------------------------------------------
    structlog.contextvars.bind_contextvars(
        region=region_name,
        pid=os.getpid(),
    )
