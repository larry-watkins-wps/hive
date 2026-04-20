"""Glia entry point — ``python -m glia`` (spec §E.1, §E.2; plan 5.10).

Wires all eight glia sub-modules plus the supervisor behind a single
:mod:`aiomqtt` connection:

1. Load :class:`~glia.registry.RegionRegistry` from ``regions_registry.yaml``.
2. Construct the docker client, sub-modules, supervisor, and MQTT client.
3. Subscribe to every system topic the supervisor routes on.
4. Dispatch inbound envelopes into the appropriate ``Supervisor.on_*``
   method via a simple topic-prefix router.
5. Race the dispatch loop against a SIGTERM/SIGINT/SIGBREAK-driven
   ``asyncio.Event`` so shutdown is graceful.

Exit-code mapping (parallels region_template's §A.4.2 convention):

+-----------------------------+------+
| Condition                   | Exit |
+=============================+======+
| clean shutdown              |  0   |
| any other uncaught error    |  1   |
| registry / config error     |  2   |
| MQTT connection failure     |  4   |
+-----------------------------+------+

Docker-events-based exit detection is a **future enhancement**. For v0,
region exits are detected via heartbeat miss (wired through
:class:`~glia.heartbeat_monitor.HeartbeatMonitor` → supervisor callback).
Wiring a ``docker_client.events()`` stream into :meth:`Supervisor.on_region_exit`
is the follow-up that will give exit-2/exit-3 → rollback its high-confidence
trigger.

Windows signal handling caveat: :meth:`asyncio.AbstractEventLoop.add_signal_handler`
raises ``NotImplementedError`` on Windows, so on win32 we register
:func:`signal.signal` handlers for ``SIGINT`` (Ctrl-C) and ``SIGBREAK``
(``CTRL_BREAK_EVENT``) and hand off to the loop via
:meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`. POSIX ``SIGTERM``
is not a real Windows signal and is not used there. We also force
:class:`asyncio.WindowsSelectorEventLoopPolicy` on win32 so that
``aiomqtt``/``paho-mqtt`` (which rely on socket reader/writer
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

import aiomqtt
import structlog
import structlog.contextvars
import structlog.typing

from glia.acl_manager import AclManager
from glia.codechange_executor import CodeChangeExecutor
from glia.heartbeat_monitor import HeartbeatMonitor
from glia.launcher import Launcher
from glia.metrics import MetricsAggregator
from glia.registry import RegionRegistry, RegistryError
from glia.rollback import Rollback
from glia.spawn_executor import SpawnExecutor
from glia.supervisor import Supervisor
from shared.message_envelope import Envelope, EnvelopeValidationError
from shared.topics import (
    SYSTEM_CODECHANGE_APPROVED,
    SYSTEM_HEARTBEAT_WILDCARD,
    SYSTEM_REGION_STATS_WILDCARD,
    SYSTEM_RESTART_REQUEST,
    SYSTEM_SLEEP_REQUEST,
    SYSTEM_SPAWN_QUERY,
    SYSTEM_SPAWN_REQUEST,
)

__all__ = ["main"]


# Exit-code constants.
_EXIT_OK = 0
_EXIT_UNHANDLED = 1
_EXIT_CONFIG = 2
_EXIT_MQTT = 4

# Topic-prefix dispatch table. Order matters only in that wildcard
# subscriptions (``+``) hit ``startswith("hive/system/heartbeat/")``
# before the exact-topic checks; the heartbeat / region_stats prefixes
# do not overlap any of the exact topics below.
_HEARTBEAT_PREFIX = "hive/system/heartbeat/"
_REGION_STATS_PREFIX = "hive/system/region_stats/"

# Every topic the supervisor can route. Listed here so the subscribe
# loop in :func:`_run` matches the dispatch table below exactly.
_SUBSCRIBED_TOPICS: tuple[str, ...] = (
    SYSTEM_HEARTBEAT_WILDCARD,
    SYSTEM_REGION_STATS_WILDCARD,
    SYSTEM_SLEEP_REQUEST,
    SYSTEM_RESTART_REQUEST,
    SYSTEM_SPAWN_REQUEST,
    SYSTEM_SPAWN_QUERY,
    SYSTEM_CODECHANGE_APPROVED,
)


def _configure_logging() -> None:
    """Configure structlog to emit JSON lines on stdout.

    Inlined rather than imported from ``region_template.logging_setup``
    because the glia container image does not bundle ``region_template``
    (see ``glia/Dockerfile``). The processor chain mirrors the one in
    spec §H.1 — ``ts`` / ``level`` / ``event`` keys, with ``warn``
    preferred over ``warning`` to match the region runtime.
    """

    def _remap_warning_to_warn(
        _logger: object, _method: str, event_dict: dict
    ) -> dict:
        if event_dict.get("level") == "warning":
            event_dict["level"] = "warn"
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _remap_warning_to_warn,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(region="glia", pid=os.getpid())


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


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event
) -> None:
    """Install OS signal handlers that set ``shutdown_event``.

    Mirrors :func:`region_template.__main__._install_signal_handlers`:

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
        def _handler(_signum: int, _frame: object) -> None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_on_event_loop)

        for sig_name in ("SIGINT", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, _handler)
        return

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_event_loop)


async def _dispatch_loop(  # noqa: PLR0912 — straight-line topic router
    mqtt_client: aiomqtt.Client,
    supervisor: Supervisor,
    log: structlog.typing.FilteringBoundLogger,
) -> None:
    """Read envelopes from ``mqtt_client.messages`` and route to supervisor.

    Topic routing:

    * ``hive/system/heartbeat/+``      → :meth:`Supervisor.on_heartbeat`
    * ``hive/system/region_stats/+``   → :meth:`Supervisor.on_region_stats`
    * ``hive/system/sleep/request``    → :meth:`Supervisor.on_sleep_request`
    * ``hive/system/restart/request``  → :meth:`Supervisor.on_restart_request`
    * ``hive/system/spawn/request``    → :meth:`Supervisor.on_spawn_request`
    * ``hive/system/spawn/query``      → :meth:`Supervisor.on_spawn_query`
    * ``hive/system/codechange/approved`` → :meth:`Supervisor.on_codechange_approved`

    Malformed envelopes are logged and dropped — the loop never raises on
    a bad payload.
    """
    async for message in mqtt_client.messages:
        topic = str(message.topic)
        payload = message.payload
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        elif not isinstance(payload, (bytes, bytearray)):
            # aiomqtt may deliver int/float for numeric payloads; those
            # are not envelopes. Skip them rather than crash the loop.
            log.warning("glia.main.bad_payload_type", topic=topic, kind=type(payload).__name__)
            continue

        try:
            envelope = Envelope.from_json(bytes(payload))
        except EnvelopeValidationError as exc:
            log.warning("glia.main.bad_envelope", topic=topic, error=str(exc))
            continue

        try:
            if topic.startswith(_HEARTBEAT_PREFIX):
                await supervisor.on_heartbeat(envelope, retained=bool(message.retain))
            elif topic.startswith(_REGION_STATS_PREFIX):
                await supervisor.on_region_stats(envelope)
            elif topic == SYSTEM_SLEEP_REQUEST:
                await supervisor.on_sleep_request(envelope)
            elif topic == SYSTEM_RESTART_REQUEST:
                await supervisor.on_restart_request(envelope)
            elif topic == SYSTEM_SPAWN_REQUEST:
                await supervisor.on_spawn_request(envelope)
            elif topic == SYSTEM_SPAWN_QUERY:
                await supervisor.on_spawn_query(envelope)
            elif topic == SYSTEM_CODECHANGE_APPROVED:
                await supervisor.on_codechange_approved(envelope)
            else:
                # Unsubscribed topic leaked through (shouldn't happen).
                log.warning("glia.main.unrouted_topic", topic=topic)
        except Exception as exc:  # noqa: BLE001 — never let one bad message kill dispatch
            log.exception("glia.main.dispatch_error", topic=topic, error=str(exc))


async def _run(  # noqa: PLR0915 — linear bootstrap sequence; easier to read flat
    registry_path: Path | None,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_username: str | None,
    mqtt_password: str | None,
) -> int:
    """Bootstrap glia and run until a shutdown signal arrives.

    Returns an exit code per the module docstring's mapping.
    """
    log = structlog.get_logger("glia.main")

    # Registry.
    try:
        registry = (
            RegionRegistry.load(registry_path)
            if registry_path is not None
            else RegionRegistry.load()
        )
    except (RegistryError, OSError) as exc:
        log.error("glia.main.registry_load_failed", error=str(exc))
        return _EXIT_CONFIG

    # Docker client. Imported lazily so ``python -m glia --help`` works
    # even when the docker daemon is unreachable.
    try:
        import docker  # noqa: PLC0415

        docker_client = docker.from_env()
    except Exception as exc:  # noqa: BLE001
        log.error("glia.main.docker_client_failed", error=str(exc))
        return _EXIT_UNHANDLED

    # Sub-modules that don't need the MQTT publish callable yet.
    launcher = Launcher(registry, client=docker_client)
    heartbeat_monitor = HeartbeatMonitor()
    acl_manager = AclManager(registry, docker_client=docker_client)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    _install_signal_handlers(loop, shutdown_event)

    try:
        async with aiomqtt.Client(
            hostname=mqtt_host,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            identifier="glia",
        ) as mqtt_client:
            # Bind publish callable to this specific client instance.
            async def publish(
                envelope: Envelope, *, retain: bool = False
            ) -> None:
                await mqtt_client.publish(
                    envelope.topic,
                    payload=envelope.to_json(),
                    qos=1,
                    retain=retain,
                )

            rollback = Rollback(launcher, publish=publish)
            spawn_executor = SpawnExecutor(
                launcher, registry, acl_manager, publish=publish
            )
            codechange_executor = CodeChangeExecutor(
                launcher,
                registry,
                publish=publish,
                docker_client=docker_client,
            )
            metrics = MetricsAggregator(
                registry,
                heartbeat_monitor,
                publish=publish,
                docker_client=docker_client,
            )
            supervisor = Supervisor(
                registry,
                launcher,
                heartbeat_monitor,
                acl_manager,
                rollback,
                spawn_executor,
                codechange_executor,
                metrics,
                publish=publish,
            )

            await supervisor.start()
            try:
                for topic in _SUBSCRIBED_TOPICS:
                    await mqtt_client.subscribe(topic, qos=1)

                log.info(
                    "glia.main.started",
                    mqtt_host=mqtt_host,
                    mqtt_port=mqtt_port,
                    subscribed=list(_SUBSCRIBED_TOPICS),
                )

                dispatch_task = asyncio.create_task(
                    _dispatch_loop(mqtt_client, supervisor, log),
                    name="glia_dispatch",
                )
                signal_task = asyncio.create_task(
                    shutdown_event.wait(),
                    name="glia_signal",
                )

                try:
                    done, pending = await asyncio.wait(
                        {dispatch_task, signal_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    done, pending = set(), {dispatch_task, signal_task}

                for task in pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

                # Surface an exception from the dispatch task (other
                # than cancellation) as exit 1.
                exit_code = _EXIT_OK
                if dispatch_task in done:
                    exc = dispatch_task.exception()
                    if exc is not None and not isinstance(
                        exc, asyncio.CancelledError
                    ):
                        log.error(
                            "glia.main.dispatch_task_crashed", error=str(exc)
                        )
                        exit_code = _EXIT_UNHANDLED

                return exit_code
            finally:
                # Supervisor teardown must run even if the dispatch loop
                # raised — cancels in-flight restart backoffs and stops
                # metrics / heartbeat timers.
                with contextlib.suppress(Exception):
                    await supervisor.stop()
    except aiomqtt.MqttError as exc:
        log.error("glia.main.mqtt_error", error=str(exc))
        return _EXIT_MQTT


def main() -> None:
    """CLI entry point — argparse + ``asyncio.run`` + ``sys.exit``."""
    parser = argparse.ArgumentParser(prog="glia")
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help=(
            "Path to regions_registry.yaml. "
            "Omit to use the packaged default at glia/regions_registry.yaml."
        ),
    )
    parser.add_argument(
        "--mqtt-host",
        default=os.environ.get("MQTT_HOST", "broker"),
        help="MQTT broker hostname (env: MQTT_HOST, default: broker).",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=int(os.environ.get("MQTT_PORT", "1883")),
        help="MQTT broker port (env: MQTT_PORT, default: 1883).",
    )
    parser.add_argument(
        "--mqtt-username",
        default=os.environ.get("MQTT_USERNAME", "glia"),
        help="MQTT username (env: MQTT_USERNAME, default: glia).",
    )
    parser.add_argument(
        "--mqtt-password",
        default=os.environ.get("MQTT_PASSWORD"),
        help=(
            "MQTT password (env: MQTT_PASSWORD). Compose should inject "
            "glia's password — spec §F.4 names the host-side var "
            "MQTT_PASSWORD_GLIA, but inside the container it reaches "
            "this process as MQTT_PASSWORD."
        ),
    )
    args = parser.parse_args()

    # Configure JSON logging BEFORE any async work so bootstrap errors
    # render correctly.
    _configure_logging()

    _install_selector_loop_policy_on_win32()

    try:
        exit_code = asyncio.run(
            _run(
                args.registry,
                args.mqtt_host,
                args.mqtt_port,
                args.mqtt_username,
                args.mqtt_password,
            )
        )
    except KeyboardInterrupt:
        # Windows Ctrl-C fallback — no signal handler, so asyncio.run
        # re-raises. Treat as a clean shutdown.
        exit_code = _EXIT_OK

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
