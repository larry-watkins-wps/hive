"""Region runtime entry point — ``python -m region_template`` (spec §A.3.2).

Thin wrapper around :class:`region_template.runtime.RegionRuntime`:

1. Parse ``--config <path>``.
2. Configure structlog early so any bootstrap-time error is logged as JSON.
3. Construct ``RegionRuntime(config_path)`` (which itself calls
   :func:`region_template.config_loader.load_config` so missing/invalid
   config is surfaced before MQTT retry budget is spent).
4. Install SIGTERM/SIGINT handlers that trigger graceful shutdown via an
   :class:`asyncio.Event`.
5. ``await runtime.bootstrap()`` then ``await runtime.run()``; on signal or
   runtime completion call ``runtime.shutdown(reason)``.

Exit code mapping (spec §A.4.2 / §A.12):

+-----------------------------+------+
| Condition                   | Exit |
+=============================+======+
| clean shutdown              |  0   |
| any other uncaught error    |  1   |
| :class:`ConfigError`        |  2   |
| :class:`GitError`           |  3   |
| :class:`ConnectionError`    |  4   |
+-----------------------------+------+

Plan-side convenience: if ``--config`` is omitted but ``HIVE_REGION`` is
set in the environment, the path is resolved to
``/hive/region/config.yaml`` (the per-container bind-mount path used by
the docker-compose file from spec §F.3) or, with ``--no-docker``,
``regions/<HIVE_REGION>/config.yaml`` relative to the current working
directory. This keeps the compose flow a single env-var flip and is
documented here, not in the spec.

Windows signal handling caveat: :meth:`asyncio.AbstractEventLoop.add_signal_handler`
raises ``NotImplementedError`` on Windows, so on win32 we register
:func:`signal.signal` handlers for ``SIGINT`` (Ctrl-C) and ``SIGBREAK``
(``CTRL_BREAK_EVENT``) which hand off to the loop via
:meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`. POSIX ``SIGTERM``
is not a real Windows signal and is not used there.

We also force :class:`asyncio.WindowsSelectorEventLoopPolicy` on win32 so
that ``aiomqtt``/``paho-mqtt`` (which rely on socket-reader/writer
registration) work — the default Proactor policy does not implement
``add_reader``/``add_writer``.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path

import structlog

from region_template.errors import ConfigError, GitError
from region_template.errors import ConnectionError as HiveConnectionError
from region_template.logging_setup import configure_logging
from region_template.runtime import RegionRuntime

__all__ = ["main"]


# Exit-code constants (spec §A.4.2 / §A.12).
_EXIT_OK = 0
_EXIT_UNHANDLED = 1
_EXIT_CONFIG_ERROR = 2
_EXIT_GIT_ERROR = 3
_EXIT_CONNECTION_ERROR = 4

# Docker bind-mount convention from spec §F.3 — each region container has
# its config.yaml mounted at this fixed path regardless of region name.
_DOCKER_CONFIG_PATH = Path("/hive/region/config.yaml")


def _resolve_env_config(no_docker: bool) -> Path | None:
    """Return the config path implied by ``HIVE_REGION`` env, or ``None``.

    * ``HIVE_REGION`` unset → ``None`` (caller must pass ``--config``).
    * ``--no-docker`` → ``regions/<name>/config.yaml`` (CWD-relative).
    * Otherwise → ``/hive/region/config.yaml`` (Docker convention §F.3).
    """
    name = os.environ.get("HIVE_REGION")
    if not name:
        return None
    if no_docker:
        return Path("regions") / name / "config.yaml"
    return _DOCKER_CONFIG_PATH


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event
) -> None:
    """Install OS signal handlers that set ``shutdown_event``.

    * POSIX: :meth:`asyncio.AbstractEventLoop.add_signal_handler` for both
      SIGTERM and SIGINT — fires inside the loop thread.
    * Windows: :func:`signal.signal` for SIGINT (Ctrl-C) and SIGBREAK
      (Ctrl-Break / ``CTRL_BREAK_EVENT``). The stdlib handler runs in the
      main thread with the loop paused; we use
      :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe` to wake the
      loop and set the event from the right side of the fence.

    Best-effort on both paths — ``NotImplementedError`` / ``ValueError``
    from the installer is suppressed so test harnesses running loops from
    non-main threads don't fail.
    """

    def _on_event_loop() -> None:
        shutdown_event.set()

    if sys.platform == "win32":
        # signal.signal may only be called from the main thread; tests
        # that run _main on a helper thread will silently skip.
        def _handler(_signum: int, _frame: object) -> None:
            # Signal handler runs in a re-entrant context; hand off to
            # the loop immediately.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_on_event_loop)

        for sig_name in ("SIGINT", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, _handler)
        return

    # POSIX path.
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_event_loop)


async def _main(config_path: Path) -> int:
    """Bootstrap + run a :class:`RegionRuntime` until shutdown.

    Returns an exit code per the mapping in the module docstring. Catches
    the three fatal bootstrap exceptions explicitly and lets everything
    else fall through as exit 1.
    """
    log = structlog.get_logger("region_template.main")

    # RegionRuntime(__init__) calls load_config, so ConfigError can surface
    # before we enter any async scope. Catch it here for a clean exit 2.
    try:
        runtime = RegionRuntime(config_path)
    except ConfigError as exc:
        log.error("region_entry_config_error", error=str(exc))
        return _EXIT_CONFIG_ERROR

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    _install_signal_handlers(loop, shutdown_event)

    # Bootstrap — map the three documented fatal exceptions to exit codes.
    try:
        await runtime.bootstrap()
    except ConfigError as exc:
        log.error("region_bootstrap_config_error", error=str(exc))
        return _EXIT_CONFIG_ERROR
    except GitError as exc:
        log.error("region_bootstrap_git_error", error=str(exc))
        return _EXIT_GIT_ERROR
    except HiveConnectionError as exc:
        log.error("region_bootstrap_connection_error", error=str(exc))
        return _EXIT_CONNECTION_ERROR

    # Main loop: race runtime.run() against the shutdown signal. Whichever
    # completes first triggers the graceful shutdown path.
    run_task = asyncio.create_task(runtime.run(), name="runtime_run")
    signal_task = asyncio.create_task(
        shutdown_event.wait(), name="runtime_signal_wait"
    )
    try:
        done, pending = await asyncio.wait(
            {run_task, signal_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        # e.g. the embedding loop was cancelled from outside.
        done, pending = set(), {run_task, signal_task}

    # Determine shutdown reason from which task finished first.
    reason = "signal" if signal_task in done else "run_returned"

    # Cancel the not-yet-done task so shutdown isn't blocked on it.
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # Graceful teardown — idempotent; runtime.shutdown guards against
    # double-invocation internally.
    with contextlib.suppress(Exception):
        await runtime.shutdown(reason)

    # Surface run_task's exception, if any, rather than masking it with a
    # clean-exit 0. Cancellation is expected when the signal wins the race.
    if run_task in done:
        exc = run_task.exception()
        if exc is not None and not isinstance(exc, asyncio.CancelledError):
            log.error("region_run_error", error=str(exc))
            return _EXIT_UNHANDLED

    return _EXIT_OK


def _install_selector_loop_policy_on_win32() -> None:
    """On Windows, force the Selector event-loop policy.

    The default on win32 is :class:`asyncio.WindowsProactorEventLoopPolicy`,
    which does not implement ``add_reader`` / ``add_writer``. The MQTT stack
    (``aiomqtt`` → ``paho-mqtt``) relies on those methods to register its
    socket, so a Proactor loop raises ``NotImplementedError`` during
    bootstrap. POSIX is untouched.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    """CLI entry point — argparse + ``asyncio.run`` + ``sys.exit``."""
    parser = argparse.ArgumentParser(prog="region_template")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to the region's config.yaml. Omit to resolve via HIVE_REGION.",
    )
    parser.add_argument(
        "--no-docker",
        action="store_true",
        help=(
            "When --config is omitted and HIVE_REGION is set, resolve the "
            "config to regions/<HIVE_REGION>/config.yaml (CWD-relative) "
            "instead of the Docker bind-mount path /hive/region/config.yaml."
        ),
    )
    args = parser.parse_args()

    # Configure logging BEFORE construction so bootstrap errors render as
    # JSON. ``region`` contextvar is initially a placeholder; runtime's own
    # bootstrap step 2 rebinds it to the real name from config.
    configure_logging(region_name="<bootstrap>", level="info")

    # Ensure the MQTT stack gets an event loop with socket-registration
    # support (a no-op on POSIX; selector-policy override on Windows).
    _install_selector_loop_policy_on_win32()

    config_path: Path | None = args.config
    if config_path is None:
        config_path = _resolve_env_config(args.no_docker)
    if config_path is None:
        parser.error(
            "--config is required when HIVE_REGION is not set in the "
            "environment"
        )

    try:
        exit_code = asyncio.run(_main(config_path))
    except KeyboardInterrupt:
        # Windows Ctrl-C fallback — no signal handler, so asyncio.run
        # re-raises. Treat as a clean shutdown.
        exit_code = _EXIT_OK

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
