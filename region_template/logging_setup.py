"""Logging configuration for Hive region runtime — spec §H.1.

Sets up structlog with a JSON-line processor chain and routes stdlib
``logging`` through the same pipeline so third-party libraries (httpx,
paho-mqtt, …) appear in structured output.

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
        - Binds ``region`` and ``pid`` as contextvars.
        - Routes stdlib ``logging`` through structlog (for third-party libs
          like httpx, paho-mqtt, etc.).

    Idempotent: safe to call multiple times (e.g., in tests).
    """
    global _configured  # noqa: PLW0603

    # Normalise level to uppercase for stdlib logging, lowercase for structlog.
    level_upper = level.upper()
    # Convert 'WARN' to 'WARNING' for stdlib which doesn't know 'WARN'.
    stdlib_level = level_upper if level_upper != "WARN" else "WARNING"
    numeric_level = getattr(logging, stdlib_level, logging.INFO)

    if not _configured:
        # ------------------------------------------------------------------
        # 1. Configure stdlib logging — plain %(message)s so structlog owns
        #    formatting; third-party libs share the stdout stream.
        # ------------------------------------------------------------------
        logging.basicConfig(
            level=numeric_level,
            stream=sys.stdout,
            format="%(message)s",
        )

        # ------------------------------------------------------------------
        # 2. Configure structlog processor chain (§H.1).
        # ------------------------------------------------------------------
        structlog.configure(
            processors=[
                # Pick up correlation_id, phase, and other contextvars.
                structlog.contextvars.merge_contextvars,
                # Add lowercase 'level' key (then remap warning->warn).
                structlog.processors.add_log_level,
                _remap_warning_to_warn,
                # ISO-8601 UTC timestamp under the spec key 'ts'.
                structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
                # Render exception tracebacks into the event dict.
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                # Final renderer: one JSON object per line.
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
            cache_logger_on_first_use=True,
        )

        _configured = True
    else:
        # Already configured — only update the stdlib root level so that
        # a repeated call with a different level still takes effect.
        logging.getLogger().setLevel(numeric_level)

    # ------------------------------------------------------------------
    # 3. Bind per-region context into every subsequent log line.
    #    Done unconditionally so repeated calls update the bound values.
    # ------------------------------------------------------------------
    structlog.contextvars.bind_contextvars(
        region=region_name,
        pid=os.getpid(),
    )
