"""``hive watch <pattern>`` — subscribe to an MQTT topic and pretty-print envelopes.

Spec §H.3 (lines 4089-4104). Operator tool for observing bus traffic.

Two modes:

* **Live tail** (default): subscribe and stream every matching message until
  ``--timeout`` expires or Ctrl-C. Without ``--timeout``, runs until
  interrupted.
* **Retained dump** (``--retained``): subscribe, print only messages with the
  retain bit set, and exit when the broker has flushed its retained set
  (heuristic: ~500ms of silence) or ``--timeout`` elapses (default 5s).

Invocation:
    python -m tools.dbg.hive_watch <pattern> [--host HOST] [--port N]
        [--retained] [--timeout SEC]

``<pattern>`` may be:
* A literal MQTT topic filter (e.g., ``hive/cognitive/#``, ``hive/+/state``).
* A convenience alias: ``modulators``, ``attention``, ``self``, ``metrics``.

Anything containing ``/``, ``#``, or ``+`` is treated as a literal.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import aiomqtt
import typer

from shared.message_envelope import Envelope, EnvelopeValidationError

# aiomqtt needs add_reader/add_writer on Windows; the Proactor loop doesn't
# support those, so force the Selector policy at import time.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------------------
# Aliases — sugar for common topic patterns (spec §H.3 examples).
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "modulators": "hive/modulator/#",
    "attention": "hive/attention/#",
    "self": "hive/self/#",
    "metrics": "hive/system/metrics/#",
}

# Preview length for payload data in the output.
_PREVIEW_LEN = 80

# Default hard cap on --retained mode when --timeout is omitted.
_DEFAULT_RETAINED_TIMEOUT_S = 5.0

# Silence window after which we consider retained-flush complete.
_RETAINED_QUIET_WINDOW_S = 0.5

# Exit codes.
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Pattern resolution
# ---------------------------------------------------------------------------


def _resolve_pattern(arg: str) -> str | None:
    """Resolve ``arg`` to an MQTT topic filter.

    Returns the filter string, or ``None`` if ``arg`` is neither a literal
    (contains ``/``, ``#``, or ``+``) nor a known alias.
    """
    if any(ch in arg for ch in ("/", "#", "+")):
        return arg
    return _ALIASES.get(arg)


def _truncate(text: str, limit: int = _PREVIEW_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_line(env: Envelope) -> str:
    """One-line pretty-print of an envelope.

    Format: ``<ts>  <source>  <topic>  <content_type>  <preview>``
    """
    ct = env.payload.content_type
    data = env.payload.data
    preview = (
        f'"{_truncate(str(data))}"' if ct == "text/plain" else _truncate(str(data))
    )
    return f"{env.timestamp}  {env.source_region}  {env.topic}  {ct}  {preview}"


# ---------------------------------------------------------------------------
# Async worker
# ---------------------------------------------------------------------------


async def _consume(
    client: Any,
    *,
    retained: bool,
    timeout: float | None,
) -> None:
    """Pull messages off ``client.messages`` and print them.

    Exits when:

    * The async iterator raises ``StopAsyncIteration`` (test fakes signal
      end-of-stream this way).
    * ``timeout`` elapses.
    * (``retained=True`` only) no new message arrives within
      ``_RETAINED_QUIET_WINDOW_S``.
    """

    async def _iter() -> None:
        async for msg in client.messages:
            _handle_message(msg, retained_only=retained)

    if retained:
        hard_cap = timeout if timeout is not None else _DEFAULT_RETAINED_TIMEOUT_S
        await _drain_retained(client, hard_cap=hard_cap)
        return

    if timeout is not None:
        try:
            await asyncio.wait_for(_iter(), timeout=timeout)
        except TimeoutError:
            return
        except StopAsyncIteration:
            return
    else:
        try:
            await _iter()
        except StopAsyncIteration:
            return


async def _drain_retained(client: Any, *, hard_cap: float) -> None:
    """Collect retained messages until quiet window or ``hard_cap`` expires."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + hard_cap
    iterator = client.messages.__aiter__()

    while True:
        now = loop.time()
        remaining = deadline - now
        if remaining <= 0:
            return
        wait = min(_RETAINED_QUIET_WINDOW_S, remaining)
        try:
            msg = await asyncio.wait_for(iterator.__anext__(), timeout=wait)
        except TimeoutError:
            # Quiet window elapsed — assume retained set is flushed.
            return
        except StopAsyncIteration:
            return
        _handle_message(msg, retained_only=True)


def _handle_message(msg: Any, *, retained_only: bool) -> None:
    if retained_only and not getattr(msg, "retain", False):
        return
    payload: bytes = msg.payload
    try:
        env = Envelope.from_json(payload)
    except EnvelopeValidationError as exc:
        typer.echo(f"{msg.topic}  <invalid envelope>  {exc}")
        return
    typer.echo(_format_line(env))


# ---------------------------------------------------------------------------
# Public entry point (tested directly)
# ---------------------------------------------------------------------------


def run(
    pattern: str,
    *,
    host: str,
    port: int,
    retained: bool,
    timeout: float | None,
    client_factory: Callable[..., Any] = aiomqtt.Client,
) -> int:
    """Execute one ``hive watch`` invocation. Returns a process exit code."""
    resolved = _resolve_pattern(pattern)
    if resolved is None:
        known = ", ".join(sorted(_ALIASES))
        typer.echo(
            f"error: unknown alias '{pattern}'. "
            f"Known aliases: {known}. "
            "Pass a literal MQTT topic filter (containing '/', '#', or '+') instead.",
            err=True,
        )
        return _EXIT_USAGE

    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")

    kwargs: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "identifier": f"hive-watch-{uuid4().hex[:8]}",
    }
    if username is not None:
        kwargs["username"] = username
    if password is not None:
        kwargs["password"] = password

    exit_code = _EXIT_OK

    async def _main() -> None:
        nonlocal exit_code
        try:
            async with client_factory(**kwargs) as client:
                await client.subscribe(resolved)
                try:
                    await _consume(client, retained=retained, timeout=timeout)
                except KeyboardInterrupt:  # pragma: no cover - interactive only
                    return
        except aiomqtt.MqttError as exc:
            # §H.3: human-facing wrapper — no tracebacks on broker hiccups.
            typer.echo(f"broker error: {exc}", err=True)
            exit_code = _EXIT_ERROR

    with contextlib.suppress(KeyboardInterrupt):  # pragma: no cover
        asyncio.run(_main())
    return exit_code


# ---------------------------------------------------------------------------
# Typer CLI
# ---------------------------------------------------------------------------


app = typer.Typer(
    add_completion=False,
    help="Subscribe to an MQTT topic pattern and pretty-print envelopes.",
    no_args_is_help=True,
)


@app.command(name="watch", help="Watch an MQTT topic pattern (spec §H.3).")
def _watch_cmd(
    pattern: str = typer.Argument(
        ...,
        help=(
            "Topic filter or alias. Aliases: modulators, attention, self, "
            "metrics. Anything containing '/', '#', or '+' is treated as a "
            "literal MQTT filter."
        ),
    ),
    host: str = typer.Option("localhost", "--host", help="MQTT broker host."),
    port: int = typer.Option(1883, "--port", help="MQTT broker port."),
    retained: bool = typer.Option(
        False,
        "--retained",
        help="One-shot dump of retained messages; exit when drained.",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help=(
            "Hard exit after N seconds. Default: none in live mode, 5s in "
            "--retained mode."
        ),
    ),
) -> None:
    rc = run(
        pattern,
        host=host,
        port=port,
        retained=retained,
        timeout=timeout,
    )
    raise typer.Exit(code=rc)


def main() -> None:  # pragma: no cover - trivial
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
